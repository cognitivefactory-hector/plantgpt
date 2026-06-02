# PlantGPT — Django + OR-Tools. python:3.12-slim has manylinux wheels for ortools,
# so no build toolchain is needed (verified in M0).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first for layer caching. pyproject.toml is the single source of deps.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY . .

# collectstatic runs at build so the image is self-contained (whitenoise serves them).
# A dummy SECRET_KEY is fine here; it is never used at runtime.
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=sqlite:// \
    python manage.py collectstatic --noinput

EXPOSE 8000

# entrypoint waits for Postgres, migrates, then execs the CMD.
# CMD uses sh -c so ${PORT} expands — Render injects its own PORT; compose uses 8000.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3"]
