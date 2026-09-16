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

# Django 5.2 对非 HTTPS POST 启用 Origin 校验；nginx 转发时 Host 不带端口，
# 必须把带端口的对外源站加入信任列表，否则站内通知等 POST 接口返回 403。
CSRF_TRUSTED_ORIGINS = env.list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    default=['http://192.168.30.190:8080', 'http://localhost:8080'],
)


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
    "iwork.middleware.TargetSubmissionGateMiddleware",  # 当前负责人必须先提交今日目标
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

# 当前进程角色：web 禁止远程库，celery/management 允许受控只读访问。
IWORK_PROCESS_ROLE = env('IWORK_PROCESS_ROLE', default='web').lower()
if IWORK_PROCESS_ROLE not in {'web', 'celery', 'management'}:
    raise ValueError('IWORK_PROCESS_ROLE 必须是 web、celery 或 management')

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
        'ENGINE': 'iwork.db_backends.guarded_mysql',
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

# 应用部署在 nginx 子路径 /iwork/ 下；staticfiles 会把 STATIC_URL 规范化为
# 根绝对路径，因此必须显式携带子路径前缀，浏览器才能把静态请求路由回本应用。
STATIC_URL = env('DJANGO_STATIC_URL', default='/iwork/static/')

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
IWORK_ADMIN_GROUPS = env.list(
    'IWORK_ADMIN_GROUPS',
    default=['admin', '/admin'],
)
IWORK_DEDICATED_ADMIN_GROUPS = env.list(
    'IWORK_DEDICATED_ADMIN_GROUPS',
    default=['iwork-admin', '/iwork-admin'],
)
IWORK_TARGET_SUBMISSION_DEFAULT_DEADLINE = env(
    'IWORK_TARGET_SUBMISSION_DEFAULT_DEADLINE',
    default='09:00',
)
IWORK_TARGET_DEFAULT_WORK_HOURS = env.float(
    'IWORK_TARGET_DEFAULT_WORK_HOURS',
    default=10.0,
)
IWORK_TARGET_MAX_WORK_HOURS = env.float(
    'IWORK_TARGET_MAX_WORK_HOURS',
    default=24.0,
)
IWORK_TARGET_MIN_WORK_MINUTES = env.int(
    'IWORK_TARGET_MIN_WORK_MINUTES',
    default=1,
)
IWORK_ACCOUNT_ACCESS_VALIDATION_URL = env(
    'IWORK_ACCOUNT_ACCESS_VALIDATION_URL',
    default='http://DKT_kc_nginx:8080/api/management/iwork/accounts/',
)
IWORK_ACCOUNT_ACCESS_VALIDATION_HOST_HEADER = env(
    'IWORK_ACCOUNT_ACCESS_VALIDATION_HOST_HEADER',
    default='localhost',
)
IWORK_ACCOUNT_ACCESS_VALIDATION_TIMEOUT_SECONDS = env.float(
    'IWORK_ACCOUNT_ACCESS_VALIDATION_TIMEOUT_SECONDS',
    default=5.0,
)
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
# Broker 提交前的短请求锁；提交失败且 Redis 暂不可用时可快速自愈。
HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT = env.int(
    'HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT',
    default=30,
)
HISTORY_SNAPSHOT_REQUEST_RENEW_INTERVAL = env.float(
    'HISTORY_SNAPSHOT_REQUEST_RENEW_INTERVAL',
    default=10.0,
)

# 生产订单 SQLite 快照导入配置。
PRODUCTION_ORDERS_SQLITE_PATH = BASE_DIR / 'sqlite' / 'production_orders.db'
PRODUCTION_ORDERS_IMPORT_BATCH_SIZE = 1000
PRODUCTION_ORDERS_PROGRESS_INTERVAL = 5000

# 实时与详情缓存按曼谷业务日期隔离，避免跨午夜的旧任务覆盖新数据。
REALTIME_PROCESS_LIST_CACHE_PREFIX = 'stats:realtime:_process_list'
DETAIL_CACHE_PREFIX = 'stats:detail:v5'
PRODUCT_OVERVIEW_CACHE_NAME = 'product_overview'
FLOW_DETAIL_CACHE_NAME = 'flow'

# 版本化实时读模型配置。新键与既有缓存并存，发布失败时保留旧 current。
READ_MODEL_CACHE_PREFIX = 'iwork:read:v1'
READ_MODEL_SCHEMA_VERSION = 1
READ_MODEL_RETENTION_SECONDS = env.int('READ_MODEL_RETENTION_SECONDS', default=172800)
READ_MODEL_STALE_AFTER_SECONDS = env.int('READ_MODEL_STALE_AFTER_SECONDS', default=120)
READ_MODEL_MAX_STALE_SECONDS = env.int('READ_MODEL_MAX_STALE_SECONDS', default=600)
READ_MODEL_PUBLISH_LOCK_SECONDS = env.int('READ_MODEL_PUBLISH_LOCK_SECONDS', default=60)
READ_MODEL_REFRESH_LOCK_SECONDS = env.int('READ_MODEL_REFRESH_LOCK_SECONDS', default=120)

# ======
# SSE 事件通知与背压配置
SSE_NOTIFICATION_CHANNEL = env(
    'SSE_NOTIFICATION_CHANNEL',
    default='iwork:read:v1:published',
)
SSE_CLIENT_QUEUE_SIZE = 1
SSE_PAYLOAD_CACHE_SIZE = env.int('SSE_PAYLOAD_CACHE_SIZE', default=64)
SSE_PAYLOAD_BUILD_CONCURRENCY = env.int(
    'SSE_PAYLOAD_BUILD_CONCURRENCY',
    default=4,
)
SSE_HEARTBEAT_SECONDS = env.float('SSE_HEARTBEAT_SECONDS', default=15.0)
SSE_CONNECTION_LEASE_SECONDS = env.float(
    'SSE_CONNECTION_LEASE_SECONDS',
    default=60.0,
)
ALERT_NOTIFICATION_CHANNEL = env(
    'ALERT_NOTIFICATION_CHANNEL',
    default='iwork:alerts:v1:notifications',
)
IWORK_TRUSTED_PROXY_HOSTS = env.list(
    'IWORK_TRUSTED_PROXY_HOSTS',
    default=['DKT_kc_nginx'],
)
SSE_NOTIFICATION_POLL_SECONDS = env.float(
    'SSE_NOTIFICATION_POLL_SECONDS',
    default=60.0,
)
SSE_NOTIFICATION_RETRY_MIN_SECONDS = env.float(
    'SSE_NOTIFICATION_RETRY_MIN_SECONDS',
    default=1.0,
)
SSE_NOTIFICATION_RETRY_MAX_SECONDS = env.float(
    'SSE_NOTIFICATION_RETRY_MAX_SECONDS',
    default=30.0,
)

# Flow 白名单生效工序 — 仅此工序使用 ALLOWED_FLOWS 过滤，其他工序查询全量 Flow
ALLOWED_FLOWS_STEPNO = 70

# Flow 白名单 — 生产详情仅保留这些分组（Sewing 产线命名，2026-09 数据库迁移后生效）
ALLOWED_FLOWS = [
    'Sewing-A1', 'Sewing-A2', 'Sewing-A3', 'Sewing-A4', 'Sewing-A5', 'Sewing-A8',
    'Sewing-A10', 'Sewing-A11', 'Sewing-A12', 'Sewing-A13', 'Sewing-A19',
    'Sewing-B3', 'Sewing-B4', 'Sewing-B5', 'Sewing-B6', 'Sewing-B7', 'Sewing-B8',
    'Sewing-B9', 'Sewing-B10', 'Sewing-B11', 'Sewing-B12', 'Sewing-B13',
    'Sewing-B16', 'Sewing-B17', 'Sewing-B19',
]

# 隐藏分组 — 不查询、不显示（配置具体 Flow 名称）
HIDDEN_FLOWS = []

# 实际可见分组 = 白名单 - 隐藏
VISIBLE_FLOWS = [f for f in ALLOWED_FLOWS if f not in HIDDEN_FLOWS]

# 数据库查询超时（秒）
QUERY_TIMEOUT = 45

# 月度统计缓存 TTL（30 天）
MONTHLY_CACHE_TTL = 60 * 60 * 24 * 30

# 产量看板默认配置
KANBAN_DEFAULT_STEPNO = '70'       # 默认工序筛选值
KANBAN_DEFAULT_PAGE_SIZE = 50      # 排行榜每页条数
