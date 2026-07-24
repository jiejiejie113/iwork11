from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / 'iwork' / '.env')

# 初始化统一日志系统（Django 组件）
from iwork.logger_config import setup_logging  # noqa: E402
setup_logging('DJANGO')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('DJANGO_SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DJANGO_DEBUG', default=False)

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_beat",
    "rest_framework",
    "iwork",
]

MIDDLEWARE = [
    "iwork.middleware.TrustedProxyMiddleware",  # IP 校验：仅接受 Docker 内网请求（纵深防御）
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "iwork.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "iwork.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('ACCESS_DB_NAME'),
        'USER': env('ACCESS_DB_USER'),
        'PASSWORD': env('ACCESS_DB_PASSWORD'),
        'HOST': env('ACCESS_DB_HOST'),
        'PORT': env.int('ACCESS_DB_PORT', default=3306),
        'CONN_MAX_AGE': 300,
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'connect_timeout': 10,
            'read_timeout': 30,
        },
    },
    'iwork': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('IWORK_DB_NAME'),
        'USER': env('IWORK_DB_USER'),
        'PASSWORD': env('IWORK_DB_PASSWORD'),
        'HOST': env('IWORK_DB_HOST'),
        'PORT': env.int('IWORK_DB_PORT', default=3306),
        'CONN_MAX_AGE': 300,
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'connect_timeout': 10,
            'read_timeout': 30,
        },
    },
    'iwork_local': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('LOCAL_DB_NAME'),
        'USER': env('LOCAL_DB_USER'),
        'PASSWORD': env('LOCAL_DB_PASSWORD'),
        'HOST': env('LOCAL_DB_HOST'),
        'PORT': env.int('LOCAL_DB_PORT', default=3306),
        'CONN_MAX_AGE': 300,
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'connect_timeout': 10,
            'read_timeout': 30,
        },
    },
}

DATABASE_ROUTERS = ['iwork.database_router.DatabaseRouter']
SILENCED_SYSTEM_CHECKS = ['django.db.utils.NotSupportedError'] #跳过版本检查

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Redis 缓存配置
REDIS_HOST = env('REDIS_HOST', default='127.0.0.1')
REDIS_PORT = env.int('REDIS_PORT', default=6379)

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f'redis://{REDIS_HOST}:{REDIS_PORT}/0',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'iwork',
    }
}


# Celery 配置
CELERY_BROKER_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/1'
CELERY_RESULT_BACKEND = f'redis://{REDIS_HOST}:{REDIS_PORT}/2'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
# ======
# 业务配置（统一管理，模块内通过 django.conf.settings 引用）
# iwork 的生产日期、班次和 Celery 调度统一使用曼谷时区。
IWORK_BUSINESS_TIME_ZONE = env('IWORK_BUSINESS_TIME_ZONE', default='Asia/Bangkok')
CELERY_TIMEZONE = IWORK_BUSINESS_TIME_ZONE
WORKDAY_START_MINUTE = 7 * 60
WORKDAY_LUNCH_START_MINUTE = 11 * 60
WORKDAY_LUNCH_END_MINUTE = 12 * 60

# 历史快照单日期构建锁超时；应覆盖一次完整的远程聚合与本地发布。
HISTORY_SNAPSHOT_LOCK_TIMEOUT = env.int('HISTORY_SNAPSHOT_LOCK_TIMEOUT', default=1800)
HISTORY_SNAPSHOT_LOCK_RENEW_INTERVAL = env.int(
    'HISTORY_SNAPSHOT_LOCK_RENEW_INTERVAL',
    default=60,
)

# 实时与详情缓存按曼谷业务日期隔离，避免跨午夜的旧任务覆盖新数据。
REALTIME_PROCESS_LIST_CACHE_PREFIX = 'stats:realtime:_process_list'
DETAIL_CACHE_PREFIX = 'stats:detail:v5'
PRODUCT_OVERVIEW_CACHE_NAME = 'product_overview'
FLOW_DETAIL_CACHE_NAME = 'flow'

# Flow 白名单生效工序 — 仅此工序使用 ALLOWED_FLOWS 过滤，其他工序查询全量 Flow
ALLOWED_FLOWS_STEPNO = 70

# Flow 白名单 — 生产详情仅保留这些分组
ALLOWED_FLOWS = [
    'SO11-L11A', 'SO11-L11B', 'SO11-L11D', 'SO11-L11E',
    'SO14-L14A', 'SO14-L14B', 'SO14-L14C', 'SO14-L14D',
    'SO3-L3A', 'SO3-L3B', 'SO3-L3C', 'SO3-L3D', 'SO3-L3E', 'SO3-L3F',
    'SO5-L5B', 'SO5-L5C', 'SO5-L5D', 'SO5-L5E',
    'SO8-L8A', 'SO8-L8B', 'SO8-L8C', 'SO8-L8D', 'SO8-L8E', 'SO8-L8F',
    'SO9-L9A', 'SO9-L9B', 'SO9-L9C', 'SO9-L9D',
]

# 隐藏分组 — 不查询、不显示（配置具体 Flow 名称）
HIDDEN_FLOWS = [
    'SO2-L2A', 'SO2-L2B', 'SO2-L2C', 'SO2-L2D', 'SO2-L2E', 'SO2-L2F', 'SO2-L2G',
    'SO6-L6A', 'SO6-L6B', 'SO6-L6C', 'SO6-L6D', 'SO6-L6E', 'SO6-L6F', 'SO6-L6G',
    'SO10-L10A', 'SO10-L10B', 'SO10-L10C', 'SO10-L10D', 'SO10-L10E', 'SO10-L10F', 'SO10-L10G',
]

# 实际可见分组 = 白名单 - 隐藏
VISIBLE_FLOWS = [f for f in ALLOWED_FLOWS if f not in HIDDEN_FLOWS]

# 数据库查询超时（秒）
QUERY_TIMEOUT = 45

# 月度统计缓存 TTL（30 天）
MONTHLY_CACHE_TTL = 60 * 60 * 24 * 30

# 产量看板默认配置
KANBAN_DEFAULT_STEPNO = '70'       # 默认工序筛选值
KANBAN_DEFAULT_PAGE_SIZE = 50      # 排行榜每页条数
