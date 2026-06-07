"""
Django settings for PlantGPT.

Configuration is environment-driven (12-factor) so the same image runs locally
(docker-compose) and on Render (managed Postgres + host secrets). A local .env is
loaded when present; in containers the values come from the environment directly.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env for local, non-Docker runs. No-op if the file is absent.
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-not-for-production")
DEBUG = _env_bool("DJANGO_DEBUG", "0")

# Hosts we serve from. In prod set DJANGO_ALLOWED_HOSTS to the full list, e.g.
# "plant.hector-garza.com,plantgpt.onrender.com" — the custom domain first.
_allowed = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]

# Render injects its own *.onrender.com host; always trust it too.
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST and RENDER_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_HOST)

# Behind Render (and Cloudflare) TLS terminates at the proxy; trust the forwarded
# proto, and trust the HTTPS origin of every real host we serve so POST/CSRF works
# on both the onrender.com host and the custom domain (plant.hector-garza.com).
if not DEBUG or RENDER_HOST:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [
    f"https://{h}"
    for h in ALLOWED_HOSTS
    if h not in ("*", "localhost") and not h.startswith("127.")
]

# Production hardening — applied only when actually deployed (Render sets this host),
# so the local dev server and the test client still work over plain HTTP.
if RENDER_HOST:
    SECURE_SSL_REDIRECT = True
    # ...but let Render's HTTP health probe through (it may not carry X-Forwarded-Proto).
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HSTS is opt-in (it's hard to undo on a real domain): set DJANGO_HSTS_SECONDS to enable.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "plant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# DATABASE_URL drives this; default to local Postgres if unset.
DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get(
            "DATABASE_URL", "postgres://plantgpt:plantgpt@localhost:5432/plantgpt"
        ),
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Anthropic key for the conversational layer (M5+). Absent until then.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
