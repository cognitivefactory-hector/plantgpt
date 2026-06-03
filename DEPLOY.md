# Deploying PlantGPT to Render

Dockerized Django + a managed Postgres, provisioned from [`render.yaml`](./render.yaml)
(a Render **Blueprint**). The whole thing is one image; Render builds it, runs migrations
on boot, and serves it behind a `/healthz` health check.

> **The Anthropic API key is never in this repo.** It is entered once, by hand, in the
> Render dashboard (`ANTHROPIC_API_KEY` is declared `sync: false` in `render.yaml`, which
> tells Render "don't read this from the blueprint — prompt for it"). You can deploy
> **without** it: the schedule board, solver, baseline toggle, and audit trail all work
> key-free; only Ask/Propose wait for the key.

---

## One-time setup

1. **Push to GitHub** (already done — public repo `cognitivefactory-hector/plantgpt`).
2. In the [Render dashboard](https://dashboard.render.com) → **New → Blueprint**.
3. Connect the GitHub repo and select the `main` branch. Render reads `render.yaml` and
   proposes two resources:
   - **web** — the Dockerized Django service (`plan: starter`, health check `/healthz`)
   - **plantgpt-db** — a managed Postgres (`plan: basic-256mb`)
4. Render will prompt for the one secret it can't generate:
   - **`ANTHROPIC_API_KEY`** — paste your key here, **or leave it blank for now** and add
     it later (Service → **Environment** → Add). `DJANGO_SECRET_KEY` is auto-generated and
     `DATABASE_URL` is wired from the managed Postgres automatically.
5. **Apply.** First build takes a few minutes (it installs OR-Tools wheels and runs
   `collectstatic`). When the service is **Live**, open its `*.onrender.com` URL.

## First run

On the deployed board: **Seed plant** → **Re-solve**. You'll see the Gantt, the
baseline-vs-CP-SAT toggle, and resource utilization. If you set the key, the **Ask** and
**Propose** tabs are live; otherwise they show a "set the key" notice.

## Adding / rotating the key later

Service → **Environment** → set `ANTHROPIC_API_KEY` → **Save** (Render redeploys). To
rotate, paste a new value and save. The key is masked in the dashboard and never appears
in the repo, build logs, or `git`.

## Smoke-test checklist (M8 Definition of Done)

- [ ] `https://<service>.onrender.com/healthz` returns `{"ok": true, ...}` (DB + OR-Tools)
- [ ] The board renders a feasible Gantt after Seed + Re-solve
- [ ] Baseline ⇄ CP-SAT toggle works
- [ ] (key set) **Ask** "which lots will miss their due date?" shows the query + an answer + confidence
- [ ] (key set) **Propose** an expedite → impact preview → **Approve** updates the board; a bad expedite can be **Rejected**

## Custom domain (optional)

Point `plant.hector-garza.com` at the Render service (Render → **Settings → Custom Domains**),
proxied through Cloudflare. Render terminates TLS and sets `RENDER_EXTERNAL_HOSTNAME`, which
the app already trusts (see `config/settings.py`).

## Cost guard

The agent runs on demand (button-triggered), with a prompt-cached system prompt and a
per-request `max_tokens` cap — so AI spend is bounded and only incurred when a planner
actually asks or proposes.
