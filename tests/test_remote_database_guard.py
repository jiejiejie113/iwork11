"""Web 进程远程生产数据库访问保护测试。"""

from pathlib import Path

import pytest
from django.test import override_settings

from iwork.db_guard import RemoteDatabaseAccessDenied
from iwork.db_backends.guarded_mysql.base import DatabaseWrapper


@override_settings(IWORK_PROCESS_ROLE="web")
def test_web_role_cannot_open_remote_database_connection():
    """Web 角色访问 iwork 别名时立即拒绝。"""
    wrapper = object.__new__(DatabaseWrapper)
    wrapper.alias = "iwork"

    with pytest.raises(RemoteDatabaseAccessDenied, match="禁止访问远程生产数据库"):
        wrapper._assert_remote_access_allowed()


@override_settings(IWORK_PROCESS_ROLE="celery")
def test_celery_role_can_collect_remote_database():
    """Celery 采集角色允许连接远程只读数据库。"""
    wrapper = object.__new__(DatabaseWrapper)
    wrapper.alias = "iwork"

    wrapper._assert_remote_access_allowed()


def test_api_views_do_not_import_remote_query_module():
    """静态边界阻止视图绕过统一读模型。"""
    source = (Path(__file__).parents[1] / "iwork" / "api_views.py").read_text(
        encoding="utf-8"
    )

    assert "from iwork.queries import" not in source
    assert "from iwork import queries" not in source
