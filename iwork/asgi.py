import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "iwork.settings")

from django.core.asgi import get_asgi_application

# ASGI 进程接入统一日志
from iwork.logger_config import setup_logging
setup_logging('ASGI')

application = get_asgi_application()
