"""
统一日志配置中心

所有进程入口（Django / Celery）启动时调用 setup_logging(component)，
将日志统一输出到 stdout（带组件标签）和 logs/ 目录（按天轮转）。

Usage:
    from iwork.logger_config import setup_logging
    setup_logging('DJANGO')   # 或 'CELERY'
"""

import sys
import logging
from pathlib import Path
from loguru import logger

# =====
# 日志目录配置
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# =====
# 日志格式配置
STDOUT_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>[{extra[component]:^8}]</cyan> | "
    "<level>{message}</level>"
)

FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | "
    "{level: <8} | "
    "[{extra[component]:^8}] | "
    "{name}:{function}:{line} | "
    "{message}"
)


class _ComponentFilter:
    """为每条日志注入组件名"""
    def __init__(self, component: str):
        self.component = component

    def __call__(self, record):
        record["extra"]["component"] = self.component
        return True


class _InterceptHandler(logging.Handler):
    """将 Django 标准 logging 拦截并转发到 loguru"""

    def emit(self, record: logging.LogRecord):
        level_map = {
            logging.DEBUG: "DEBUG",
            logging.INFO: "INFO",
            logging.WARNING: "WARNING",
            logging.ERROR: "ERROR",
            logging.CRITICAL: "CRITICAL",
        }
        try:
            level = level_map.get(record.levelno, "INFO")
            logger.opt(depth=6, exception=record.exc_info).log(
                level, record.getMessage()
            )
        except Exception:
            self.handleError(record)


def setup_logging(component: str = "DJANGO"):
    """
    初始化统一日志配置

    Args:
        component: 组件标识，如 'DJANGO'、'CELERY'
    """
    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 移除 loguru 默认处理器
    logger.remove()

    # stdout 处理器（带颜色 + 组件标签）
    logger.add(
        sys.stdout,
        format=STDOUT_FORMAT,
        filter=_ComponentFilter(component),
        level="DEBUG",
        colorize=True,
    )

    # 文件处理器（所有组件写入同一文件，按天轮转）
    logger.add(
        LOG_DIR / "all_{time:YYYY-MM-DD}.log",
        format=FILE_FORMAT,
        filter=_ComponentFilter(component),
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        level="DEBUG",
        enqueue=True,  # 多进程安全
    )

    # 错误单独文件
    logger.add(
        LOG_DIR / "error_{time:YYYY-MM-DD}.log",
        format=FILE_FORMAT,
        filter=_ComponentFilter(component),
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        level="ERROR",
        enqueue=True,
    )

    # 拦截 Django 标准 logging 汇入 loguru
    _intercept_django_logging(component)

    logger.info(f"日志系统初始化完成，日志目录: {LOG_DIR}")


def _intercept_django_logging(component: str):
    """将 Django 标准 logging 全部重定向到 loguru"""
    # 先清空 Django logging 的已有配置，避免重复
    logging.getLogger().handlers.clear()

    intercept_handler = _InterceptHandler()

    # 需要拦截的 logger 列表
    targets = [
        "django",
        "django.request",
        "django.server",
        "django.db.backends",
        "celery",
    ]

    for name in targets:
        django_logger = logging.getLogger(name)
        django_logger.handlers = [intercept_handler]
        django_logger.propagate = False
        django_logger.level = logging.DEBUG

    # 根 logger 也拦截（捕获未列出的）
    root = logging.getLogger()
    root.handlers = [intercept_handler]
    root.level = logging.INFO
