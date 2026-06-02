#!/bin/sh
# Wait for Postgres (when DATABASE_URL points at a host), apply migrations, then run CMD.
set -e

if [ -n "$DATABASE_URL" ] && echo "$DATABASE_URL" | grep -q "postgres"; then
  echo "Waiting for Postgres..."
  python <<'PY'
import os, time, sys
import dj_database_url
import psycopg

cfg = dj_database_url.parse(os.environ["DATABASE_URL"])
dsn = f"host={cfg['HOST']} port={cfg.get('PORT') or 5432} dbname={cfg['NAME']} user={cfg['USER']} password={cfg['PASSWORD']}"
for attempt in range(30):
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
        print("Postgres is ready.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"  not ready ({attempt + 1}/30): {exc}")
        time.sleep(1)
print("Postgres did not become ready in time.", file=sys.stderr)
sys.exit(1)
PY
fi

echo "Applying migrations..."
python manage.py migrate --noinput

exec "$@"
