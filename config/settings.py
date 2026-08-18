import os
from datetime import timedelta
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, True),
)
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('DJANGO_SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DJANGO_DEBUG')

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['127.0.0.1', 'localhost', 'testserver'])
render_hostname = env('RENDER_EXTERNAL_HOSTNAME', default='')
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Application definition

INSTALLED_APPS = [
    'accounts.apps.AccountsConfig',
    'agent.apps.AgentConfig',
    'backtest.apps.BacktestConfig',
    'dashboard.apps.DashboardConfig',
    'market.apps.MarketConfig',
    'portfolio.apps.PortfolioConfig',
    'prediction.apps.PredictionConfig',
    'watchlist.apps.WatchlistConfig',
    'corsheaders',
    'rest_framework',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

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

WSGI_APPLICATION = 'config.wsgi.application'


database_url = env('DATABASE_URL', default=None)
if database_url:
    DATABASES = {
        'default': env.db('DATABASE_URL'),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME', default=env('POSTGRES_DB', default='investment_system')),
            'USER': env('DB_USER', default=env('POSTGRES_USER', default='postgres')),
            'PASSWORD': env('DB_PASSWORD', default=env('POSTGRES_PASSWORD', default='')),
            'HOST': env('DB_HOST', default=env('POSTGRES_HOST', default='127.0.0.1')),
            'PORT': env('DB_PORT', default=env('POSTGRES_PORT', default='5432')),
        }
    }


REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

CORS_ALLOWED_ORIGINS = env.list(
    'DJANGO_CORS_ALLOWED_ORIGINS',
    default=['http://127.0.0.1:5173', 'http://localhost:5173'],
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    default=CORS_ALLOWED_ORIGINS,
)

TWELVE_DATA_API_KEY = env('TWELVE_DATA_API_KEY', default='')
TWELVE_DATA_BASE_URL = env('TWELVE_DATA_BASE_URL', default='https://api.twelvedata.com')
TWELVE_DATA_TIMEOUT_SECONDS = env.int('TWELVE_DATA_TIMEOUT_SECONDS', default=12)
TWELVE_DATA_TIMEZONE = env('TWELVE_DATA_TIMEZONE', default='America/New_York')
MARKET_DATA_CACHE_TTL_SECONDS = env.int('MARKET_DATA_CACHE_TTL_SECONDS', default=21600)
MARKET_DATA_COMPLETE_DAY_BUFFER_MINUTES = env.int('MARKET_DATA_COMPLETE_DAY_BUFFER_MINUTES', default=15)
MARKET_SUMMARY_CACHE_TTL_SECONDS = env.int('MARKET_SUMMARY_CACHE_TTL_SECONDS', default=60)
MARKET_DATA_QUOTE_CACHE_TTL_SECONDS = env.int('MARKET_DATA_QUOTE_CACHE_TTL_SECONDS', default=60)
MARKET_DATA_SYMBOL_SEARCH_CACHE_TTL_SECONDS = env.int('MARKET_DATA_SYMBOL_SEARCH_CACHE_TTL_SECONDS', default=300)
PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS = env.int('PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS', default=60)

# LLM provider configuration stays on the Django backend only.  Never expose
# these values with a VITE_ prefix or in React code.
LLM_PROVIDER = env('LLM_PROVIDER', default='deepseek')
LLM_MODEL = env('LLM_MODEL', default='deepseek-chat')
DEEPSEEK_API_KEY = env('DEEPSEEK_API_KEY', default='')
DEEPSEEK_BASE_URL = env('DEEPSEEK_BASE_URL', default='https://api.deepseek.com')
LLM_TIMEOUT_SECONDS = env.float('LLM_TIMEOUT_SECONDS', default=30)

PREDICTION_ARTIFACT_CACHE_TTL_SECONDS = env.int(
    'PREDICTION_ARTIFACT_CACHE_TTL_SECONDS',
    default=604800,
)
PREDICTION_RF_MAX_WORKERS = env.int('PREDICTION_RF_MAX_WORKERS', default=4)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'market': {
            'handlers': ['console'],
            'level': env('MARKET_DATA_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
    },
}

# Local development uses HTTP. In production, set both secure cookie flags to True.
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=False)
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE', default='Lax')
CSRF_COOKIE_SAMESITE = env('CSRF_COOKIE_SAMESITE', default='Lax')


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

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
