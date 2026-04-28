from .base import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "playto_payouts_test",
        "USER": "postgres",
        "PASSWORD": "postgres",
        "HOST": "localhost",
        "PORT": "5432",
        "ATOMIC_REQUESTS": False,
    }
}

# Use synchronous task execution in tests — but workers still called via .delay()
# Tests that need real async behavior use mock or override
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
