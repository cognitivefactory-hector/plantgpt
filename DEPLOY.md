# Publishing PlantGPT — Render + Cloudflare

Dockerized Django + a managed Postgres on **Render**, fronted by **Cloudflare** at
`plant.hector-garza.com`. Render builds the image from [`render.yaml`](./render.yaml)
(a **Blueprint**), runs migrations on boot, and serves it behind a `/healthz` health check.

> **The Anthropic API key is never in this repo.** It is entered once, by hand, in the
> Render dashboard (`ANTHROPIC_API_KEY` is `sync: false` in `render.yaml`). You can publish
> **without** it: the board, both solvers, the baseline⇄CP-SAT toggle, and the audit trail
> all work key-free; only **Ask/Propose** wait for the key, and they turn on the instant you
> add it (just an env var — no rebuild).

---

## Part 1 — Render

1. **Push to GitHub** (done — public repo `cognitivefactory-hector/plantgpt`).
2. [Render dashboard](https://dashboard.render.com) → **New → Blueprint** → connect the repo,
   select **`main`**. Render reads `render.yaml` and proposes:
   - **web** — the Dockerized Django service (`plan: starter`, health check `/healthz`)
   - **plantgpt-db** — a managed Postgres (`plan: basic-256mb`)
3. Render prompts for the one secret it can't generate:
   - **`ANTHROPIC_API_KEY`** — paste your key, **or leave it blank for now**
     (Service → **Environment** → add it any time later).
   `DJANGO_SECRET_KEY` is auto-generated; `DATABASE_URL` is wired from the managed Postgres;
   `DJANGO_ALLOWED_HOSTS` is pre-set to `plant.hector-garza.com` and the `*.onrender.com`
   host is trusted automatically.
4. **Apply.** First build takes a few minutes (OR-Tools wheels + `collectstatic`). When the
   service is **Live**, open its `https://<service>.onrender.com` URL.
5. **Verify** `https://<service>.onrender.com/healthz` → `{"ok": true, ...}`, then on the
   board: **Seed plant → Re-solve** → you should see the Gantt + utilization.

> Note the exact `<service>.onrender.com` hostname — Cloudflare points at it next.

---

## Part 2 — Cloudflare (`plant.hector-garza.com`)

The `hector-garza.com` zone is on Cloudflare. Add the subdomain and point it at Render.

### 2a. Tell Render about the domain
Render service → **Settings → Custom Domains → Add Custom Domain** → `plant.hector-garza.com`.
Render shows the CNAME target (your `<service>.onrender.com`) and a **verification** state.

### 2b. Add the DNS record in Cloudflare
Cloudflare → `hector-garza.com` → **DNS → Add record**:

| Field | Value |
|---|---|
| Type | `CNAME` |
| Name | `plant` |
| Target | `<service>.onrender.com` |
| Proxy status | **DNS only (grey cloud)** at first — see below |
| TTL | Auto |

**Verification gotcha:** while Render is issuing the TLS certificate for the custom domain,
keep the record **DNS-only (grey cloud)** so Render can validate it directly. Once Render
shows the domain **Verified / Certificate Issued**, switch the record to **Proxied (orange
cloud)** to get Cloudflare's CDN/WAF in front.

### 2c. Set the SSL mode (critical)
Cloudflare → **SSL/TLS → Overview → Full (strict)**.

- **Full (strict)** = Cloudflare→Render over HTTPS, validating Render's real certificate.
  Render always serves HTTPS, so this is correct.
- **Do NOT use "Flexible"** — Cloudflare would talk HTTP to Render while Render redirects to
  HTTPS, causing an infinite redirect loop.

### 2d. Done
Once the record is Proxied and SSL is Full (strict), `https://plant.hector-garza.com` serves
the app. Django already trusts the host and its HTTPS origin for CSRF (via
`DJANGO_ALLOWED_HOSTS` + the derived `CSRF_TRUSTED_ORIGINS`, and `SECURE_PROXY_SSL_HEADER`
for the forwarded-proto), so the Seed/Solve/Ask/Propose forms work over the proxy.

---

## Smoke-test checklist (M9 Definition of Done)

- [ ] `https://plant.hector-garza.com/healthz` → `{"ok": true, ...}` (DB + OR-Tools)
- [ ] Board renders a feasible Gantt after **Seed → Re-solve**
- [ ] Baseline ⇄ CP-SAT and by-resource ⇄ by-job toggles work
- [ ] **Seed/Re-solve POST** succeeds (no CSRF 403) over the custom domain
- [ ] (key set) **Ask** "which lots will miss their due date?" → shows the query + answer + confidence
- [ ] (key set) **Propose** an expedite → impact preview → **Approve** updates the board; a bad expedite can be **Rejected**
- [ ] Update the README **Live demo** link to `https://plant.hector-garza.com`

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `DisallowedHost ... plant.hector-garza.com` | `DJANGO_ALLOWED_HOSTS` must include it (pre-set in `render.yaml`; redeploy if you changed it). |
| CSRF `403` on Seed/Solve/Ask/Propose | The host must be in `DJANGO_ALLOWED_HOSTS` (CSRF origins are derived from it as `https://<host>`). Confirm you're on **HTTPS**. |
| Infinite redirect loop | Cloudflare SSL mode is "Flexible" — switch to **Full (strict)**. |
| Render won't verify the custom domain | Set the Cloudflare record to **DNS-only (grey cloud)** until Render issues the cert, then re-proxy. |
| Ask/Propose show "set the key" | `ANTHROPIC_API_KEY` isn't set — add it in Render → Environment (no rebuild needed). |

## Adding / rotating the key later
Service → **Environment** → set `ANTHROPIC_API_KEY` → **Save** (Render redeploys). The key is
masked in the dashboard and never appears in the repo, build logs, or `git`.

## Cost guard
The agent runs on demand (button-triggered), prompt-cached, and `max_tokens`-capped — AI spend
is bounded and only incurred when a planner actually asks or proposes.
