import django.db.backends.mysql.base

django.db.backends.mysql.base.DatabaseWrapper.check_database_version_supported = lambda self: None

from .celery import app as celery_app

__all__ = ('celery_app',)