import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from alcove.content_schema import CONTENT_COMPONENTS

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("ALCOVE_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("ALCOVE_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set ALCOVE_SECRET_KEY when ALCOVE_DEBUG=0.")
    SECRET_KEY = "development-only-alcove-secret-key-do-not-use-in-production"
ALLOWED_HOSTS = os.environ.get("ALCOVE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "alcove",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "alcove.middleware.PrivateResponsesMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("ALCOVE_DATABASE", str(DATA_DIR / "alcove.sqlite3")),
        "OPTIONS": {"timeout": 5},
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        )
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_FAILURE_VIEW = "alcove.views.csrf_failure"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "alcove.api_errors.exception_handler",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Alcove API",
    "APPEND_COMPONENTS": {"schemas": CONTENT_COMPONENTS},
    "VERSION": "1.0.0",
    "OAS_VERSION": "3.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "COMPONENT_SPLIT_PATCH": False,
    "DESCRIPTION": (
        "Private same-origin session API. Sign in at /login/ with CSRF. "
        "Send the csrftoken cookie in X-CSRFToken on POST/PATCH/DELETE. "
        "Notes use stable UUIDs and UTC timestamps. See docs/api.md."
    ),
}
