from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-only-insecure-key-change-in-prod")

DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*").split(",")

DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",  # required by auth
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_extensions",
    "django_celery_beat",
]

LOCAL_APPS = [
    "apps.merchants",
    "apps.payouts",
    "apps.ledger",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="playto_payouts"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default="postgres"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "ATOMIC_REQUESTS": False,  # We manage transactions explicitly
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"

# Celery
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True  # Acknowledge only after task completes — safe for retries
CELERY_BEAT_SCHEDULE = {
    "poll-and-dispatch-payouts": {
        "task": "payouts.poll_and_dispatch",
        "schedule": 10.0,  # every 10 seconds
    },
}

# DRF
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Conservative defaults; payout endpoint has its own stricter throttle.
        "user": "120/min",
        "anon": "20/min",
        "payout_create": "10/min",
    },
    "EXCEPTION_HANDLER": "apps.payouts.exceptions.custom_exception_handler",
}

CORS_ALLOW_ALL_ORIGINS = True

# Payout config
PAYOUT_IDEMPOTENCY_TTL_HOURS = 24
PAYOUT_MAX_ATTEMPTS = 3
PAYOUT_STUCK_THRESHOLD_SECONDS = 30

# django-ratelimit: cache backend for distributed rate limiting.
# Falls back to LocMem in dev (per-process, fine for single-worker runs).
# In prod, point CACHE_URL at redis so all gunicorn workers share the counter.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache"
        if config("CACHE_URL", default="").startswith("redis://")
        else "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": config("CACHE_URL", default="ratelimit-locmem"),
    }
}
RATELIMIT_USE_CACHE = "default"
RATELIMIT_FAIL_OPEN = False  # if cache is down, BLOCK rather than allow
