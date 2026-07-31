"""拒绝 Web 进程连接远程生产 MySQL 的数据库后端。"""

from django.conf import settings
from django.db.backends.mysql.base import DatabaseWrapper as MySQLDatabaseWrapper
from loguru import logger

from iwork.db_guard import RemoteDatabaseAccessDenied


class DatabaseWrapper(MySQLDatabaseWrapper):
    """仅允许 Celery 和管理角色使用远程 ``iwork`` 数据库。"""

    def _assert_remote_access_allowed(self) -> None:
        """检查当前进程角色是否允许访问远程生产数据库。

        Raises:
            RemoteDatabaseAccessDenied: Web 进程尝试访问远程数据库。
        """
        if settings.IWORK_PROCESS_ROLE == "web":
            logger.error("已拦截 Web 进程访问远程生产数据库: alias={}", self.alias)
            raise RemoteDatabaseAccessDenied(
                "Web 进程禁止访问远程生产数据库 iwork"
            )

    def get_new_connection(self, conn_params):
        """建立连接前执行进程角色检查。"""
        self._assert_remote_access_allowed()
        return super().get_new_connection(conn_params)

    def create_cursor(self, name=None):
        """创建游标前再次执行进程角色检查。"""
        self._assert_remote_access_allowed()
        return super().create_cursor(name)
