"""
Django settings for ZatcaEInvoiceConnector project — PostgreSQL variant.

This is a drop-in replacement for settings.py. It is IDENTICAL to the current
settings.py except for the DATABASES block, which now points at PostgreSQL
instead of SQLite. Review it, then (once you've installed PostgreSQL and set
the DB_* env vars — see docs/postgresql-migration.md) replace settings.py
with this file's contents:

    copy settings.postgresql.py settings.py

For more information on this file, see
https://docs.djangoproject.com/en/6.0/topics/settings/
"""

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# In production, set DJANGO_SECRET_KEY in the environment/.env file.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    'django-insecure-mw0gn&*)##molr4wdd9k#soxkqi2i&$7a3x)kgh^l3=n2leg=*',
)

# SECURITY WARNING: don't run with debug turned on in production!
# Defaults to True for local dev; set DJANGO_DEBUG=False in production.
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

# Comma-separated list, e.g. "invoices.mycompany.local,192.168.1.50"
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'captcha',
    'organization',
    'invoices',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ZatcaEInvoiceConnector.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ZatcaEInvoiceConnector.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
#
# --- CHANGED FROM settings.py ---
# Was SQLite (single file, whole-database write lock, no built-in backup
# tooling). Now PostgreSQL: proper per-row locking (matters for the
# Organization.select_for_update() ICV/PIH counter in hashing.py — under
# SQLite every write to the DB serializes globally regardless of which row
# it touches; under Postgres only concurrent writers to the SAME
# organization row block each other), WAL-based point-in-time recovery, and
# mature backup tooling (pg_dump / pg_basebackup) — all relevant given
# ZATCA's 6-year invoice retention requirement.
#
# All connection details come from environment variables so the same file
# works across dev/staging/production without editing code. Install the
# 'psycopg[binary]' package (already added to requirements.postgresql.txt)
# for this backend to work.

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'zatca_einvoice'),
        'USER': os.environ.get('DB_USER', 'zatca_app'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        # Reuse connections across requests instead of opening a new one
        # per request (Waitress is multi-threaded, not multi-process, so
        # this is a meaningful reduction in per-request overhead).
        'CONN_MAX_AGE': 60,
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Comma-separated list of scheme+host origins allowed to POST here, e.g.
# "https://invoices.mycompany.local". Required by Django when DEBUG=False
# and the app sits behind a reverse proxy / custom hostname.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

DEVICE_KEY_ENCRYPTION_KEY = os.environ.get("DEVICE_KEY_ENCRYPTION_KEY", "")
ZATCA_SERVER_URL = os.environ.get(
    "ZATCA_SERVER_URL",
    "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal",
)
ZATCA_COMPLIANCE_API_ENDPOINT = os.environ.get(
    "ZATCA_COMPLIANCE_API_ENDPOINT",
    "/compliance",
)
ZATCA_API_ACCEPT_VERSION = os.environ.get("ZATCA_API_ACCEPT_VERSION", "V2")
ZATCA_API_TIMEOUT_SECONDS = int(os.environ.get("ZATCA_API_TIMEOUT_SECONDS", "30"))
ZATCA_COMPLIANCE_INVOICE_CHECK_API_ENDPOINT = os.environ.get(
    "ZATCA_COMPLIANCE_INVOICE_CHECK_API_ENDPOINT", "/compliance/invoices/reporting/single")
ZATCA_PRODUCTION_CSID_API_ENDPOINT = os.environ.get(
    "ZATCA_PRODUCTION_CSID_API_ENDPOINT", "/production/csids")
ZATCA_REPORTING_API_ENDPOINT = os.environ.get(
    "ZATCA_REPORTING_API_ENDPOINT", "/invoices/reporting/single")
ZATCA_CLEARANCE_API_ENDPOINT = os.environ.get(
    "ZATCA_CLEARANCE_API_ENDPOINT", "/invoices/clearance/single")

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [],
    'UNAUTHENTICATED_USER': None,
}

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
