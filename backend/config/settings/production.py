"""
Production settings.

Hard rules enforced here:
- DEBUG must be False.
- SECRET_KEY must come from env (no insecure default reachable).
- ALLOWED_HOSTS must be explicitly set — never '*'.
- HTTPS-only cookies, HSTS, secure proxy header (assumes a TLS-terminating
  reverse proxy like Caddy/Nginx/Cloudflare in front).
- CORS allowlist (no '*').
- Sentry DSN read from env; if absent, init is a no-op.
- Structured JSON logging to stdout for log-shipping into the host's collector.

Run with: DJANGO_SETTINGS_MODULE=config.settings.production
"""

import os

from decouple import Csv, config

from .base import *  # noqa: F401, F403
from .base import REST_FRAMEWORK  # explicit re-import for in-place mutation

# ── Hard requirements ─────────────────────────────────────────────────────────
DEBUG = False

SECRET_KEY = config("SECRET_KEY")  # raises if not set — fail fast
if not SECRET_KEY or SECRET_KEY.startswith("dev-"):
    raise RuntimeError(
        "SECRET_KEY must be set to a real secret in production "
        "(not a dev placeholder)."
    )

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())
if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["*"]:
    raise RuntimeError(
        "ALLOWED_HOSTS must be an explicit comma-separated list in production "
        "(never '*')."
    )

# ── HTTPS / cookies / HSTS ────────────────────────────────────────────────────
# Assumes TLS is terminated upstream (Caddy/Nginx/Cloudflare) and the proxy
# sets X-Forwarded-Proto. If you terminate TLS in Django itself, remove the
# SECURE_PROXY_SSL_HEADER line.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # frontend needs to read it for unsafe verbs
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False  # set True only after you've submitted to hstspreload.org
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# ── CORS / CSRF allowlist ─────────────────────────────────────────────────────
# Must be set to the exact frontend origin(s). No wildcards.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", cast=Csv())

# ── DRF: stricter throttles in prod ───────────────────────────────────────────
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "user": config("THROTTLE_USER", default="60/min"),
    "anon": config("THROTTLE_ANON", default="10/min"),
    "payout_create": config("THROTTLE_PAYOUT_CREATE", default="5/min"),
}

# ── Sentry (optional, no-op if SENTRY_DSN unset) ──────────────────────────────
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        environment=config("SENTRY_ENVIRONMENT", default="production"),
        release=config("SENTRY_RELEASE", default=None),
        traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.05, cast=float),
        send_default_pii=False,  # never send PII; merchant data is sensitive
    )

# ── Logging: JSON to stdout for log shippers ──────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            # Compact single-line key=value; swap to python-json-logger if you
            # have it installed for true JSON.
            "format": (
                "ts=%(asctime)s level=%(levelname)s logger=%(name)s "
                "module=%(module)s msg=%(message)s"
            ),
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["stdout"],
        "level": config("LOG_LEVEL", default="INFO"),
    },
    "loggers": {
        "django.db.backends": {"handlers": ["stdout"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["stdout"], "level": "WARNING", "propagate": False},
    },
}

# ── Static files (collected to disk; served by reverse proxy / CDN) ───────────
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")  # noqa: F405

# ── DB connection pooling hint ────────────────────────────────────────────────
# Re-use connections within a request lifecycle.
DATABASES["default"]["CONN_MAX_AGE"] = config("DB_CONN_MAX_AGE", default=60, cast=int)  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405
