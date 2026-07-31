"""远程生产数据库进程角色保护。"""


class RemoteDatabaseAccessDenied(PermissionError):
    """当前进程角色不允许访问远程生产数据库。"""
