import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iwork.settings')

app = Celery('iwork')
app.config_from_object('django.conf:settings', namespace='CELERY')

# Celery 进程接入统一日志
from iwork.logger_config import setup_logging  # noqa: E402
setup_logging('CELERY')

app.autodiscover_tasks()

# 任务全局超时保护
app.conf.task_time_limit = 120       # hard limit（强制终止）
app.conf.task_soft_time_limit = 90   # soft limit（抛出 SoftTimeLimitExceeded）
app.conf.task_acks_late = True        # 任务完成后才确认，防止 worker 崩溃丢失任务
app.conf.worker_prefetch_multiplier = 1  # 每次只取一个任务，防止堆积

app.conf.beat_schedule = {
    'sync-dashboard-stats-every-60s': {
        'task': 'iwork.tasks.sync_dashboard_stats',
        'schedule': 60.0,
    },
    # Celery 使用曼谷业务时区，每天 03:00 重建最近历史快照。
    'snapshot-recent-history-daily': {
        'task': 'iwork.tasks.snapshot_recent_history',
        'schedule': crontab(hour=3, minute=0),
        'args': (3,),
    },
    'reconcile-target-obligations-every-minute': {
        'task': 'iwork.alerts.tasks.reconcile_target_obligations_task',
        'schedule': 60.0,
        'options': {'queue': 'alerts'},
    },
    'reconcile-alerts-every-five-minutes': {
        'task': 'iwork.alerts.tasks.reconcile_alerts_task',
        'schedule': 300.0,
        'options': {'queue': 'alerts'},
    },
}

app.conf.task_routes = {
    'iwork.alerts.tasks.*': {'queue': 'alerts'},
}
