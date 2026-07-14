import os


_TEST_ENV_DEFAULTS = {
    'DJANGO_SECRET_KEY': 'iwork-test-only-secret-key',
    'ACCESS_DB_NAME': 'test_default',
    'ACCESS_DB_USER': 'test',
    'ACCESS_DB_PASSWORD': 'test',
    'ACCESS_DB_HOST': '127.0.0.1',
    'IWORK_DB_NAME': 'test_iwork',
    'IWORK_DB_USER': 'test',
    'IWORK_DB_PASSWORD': 'test',
    'IWORK_DB_HOST': '127.0.0.1',
    'LOCAL_DB_NAME': 'test_iwork_local',
    'LOCAL_DB_USER': 'test',
    'LOCAL_DB_PASSWORD': 'test',
    'LOCAL_DB_HOST': '127.0.0.1',
}

for name, value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(name, value)

from .settings import *  # noqa: E402,F403


DATABASES = {
    alias: {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
    for alias in ('default', 'iwork', 'iwork_local')
}

CACHES = {
    'default': {
        'BACKEND': 'iwork.test_cache.PatternLocMemCache',
        'LOCATION': 'iwork-tests',
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
