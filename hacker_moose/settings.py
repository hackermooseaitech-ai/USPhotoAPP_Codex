import os
from email.utils import parseaddr
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.yahoo",
    "orders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "hacker_moose.urls"

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
                "orders.context_processors.site_chrome",
            ],
        },
    },
]

WSGI_APPLICATION = "hacker_moose.wsgi.application"

default_database_url = f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}"
DATABASES = {
    "default": dj_database_url.config(default=os.getenv("DATABASE_URL", default_database_url))
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
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "").strip()
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "").strip()
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
USE_R2 = all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_ENDPOINT_URL])

if USE_R2 or os.getenv("USE_S3", "False").lower() == "true":
    AWS_ACCESS_KEY_ID = R2_ACCESS_KEY_ID or os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = R2_SECRET_ACCESS_KEY or os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = R2_BUCKET_NAME or os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = R2_ENDPOINT_URL or os.getenv("AWS_S3_ENDPOINT_URL")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "auto" if USE_R2 else "us-east-1")
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = False if R2_PUBLIC_URL else True
    AWS_DEFAULT_ACL = None
    if R2_PUBLIC_URL:
        AWS_S3_CUSTOM_DOMAIN = R2_PUBLIC_URL.replace("https://", "").replace("http://", "")
        AWS_S3_URL_PROTOCOL = "https:"
    STORAGES["default"] = {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SITE_ID = 1
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_AUTO_SIGNUP = True


def oauth_app(provider: str) -> list[dict[str, str]]:
    client_id = os.getenv(f"{provider.upper()}_CLIENT_ID", "").strip()
    secret = os.getenv(f"{provider.upper()}_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        return []
    return [{"client_id": client_id, "secret": secret, "key": ""}]


SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APPS": oauth_app("google"),
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
    },
    "yahoo": {
        "APPS": oauth_app("yahoo"),
        "SCOPE": ["profile", "email"],
        "PROVIDER_CLASS": "orders.providers.SafeYahooProvider",
    },
}

SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000").rstrip("/")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_CENTS = int(os.getenv("STRIPE_PRICE_CENTS", "399"))

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "").replace(" ", "").strip()
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "Hacker Moose <no-reply@hackermoose.local>").strip()
DEFAULT_FROM_EMAIL_ADDRESS = parseaddr(DEFAULT_FROM_EMAIL)[1]
if EMAIL_HOST_PASSWORD and not EMAIL_HOST:
    EMAIL_HOST = "smtp.gmail.com"
if EMAIL_HOST_PASSWORD and not EMAIL_HOST_USER and DEFAULT_FROM_EMAIL_ADDRESS:
    EMAIL_HOST_USER = DEFAULT_FROM_EMAIL_ADDRESS
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", DEFAULT_FROM_EMAIL).strip()
ADMIN_TEST_TOKEN = os.getenv("ADMIN_TEST_TOKEN", "").strip()
USE_LOCAL_BACKGROUND_REMOVAL = os.getenv("USE_LOCAL_BACKGROUND_REMOVAL", "True").lower() == "true"
