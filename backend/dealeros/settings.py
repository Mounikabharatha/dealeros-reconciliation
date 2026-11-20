"""Django settings for the DealerOS reconciliation slice.

Everything that differs between laptops comes from environment variables, so
nothing secret is committed. See .env.example at the repo root.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# Local-only take-home: a fixed dev key is fine, but it can be overridden.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-secret-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "recon",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "dealeros.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]
WSGI_APPLICATION = "dealeros.wsgi.application"

# PostgreSQL is required: tenant isolation is enforced with Row-Level Security.
# Empty USER/HOST/PASSWORD fall through to libpq defaults (your OS user over the
# local socket), which is how Homebrew and Postgres.app installs work out of the box.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "dealeros"),
        "USER": os.environ.get("POSTGRES_USER", ""),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", ""),
        "PORT": os.environ.get("POSTGRES_PORT", ""),
        # Close the connection after every request; the role/tenant context is
        # per-transaction anyway, but this keeps nothing lingering between users.
        "CONN_MAX_AGE": 0,
    }
}

# The restricted database role every application query runs as (see recon/db.py).
DEALEROS_APP_ROLE = "dealeros_app"

TEST_RUNNER = "recon.testrunner.RestrictedRoleTestRunner"

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_DIR = REPO_ROOT / "data"

# The React dev server runs on 5173 and proxies /api to Django, so the browser
# sees a single origin; these settings only matter if you call the API directly.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
