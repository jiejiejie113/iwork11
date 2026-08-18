from django.conf import settings

from iwork.db_guard import RemoteDatabaseAccessDenied


class DatabaseRouter:
    """
    数据库路由器：
    - default: Django 系统权限库（读写）
    - iwork: 业务生产数据库（只读）
    - iwork_local: 本地业务数据库（读写）
    """

    iwork_app_labels = ['iwork']
    # 路由到 iwork_local 的模型（读写 + 允许迁移）
    local_models = {
        'localpytckreg3',
        'targetproduction',
        'grouptargetproduction',
        'productionorder',
        'igarmentproductionorder',
        'historicalproductionfact',
        'historicalstepsnapshot',
        'historicalsyncstate',
        'iworkprincipal',
        'managedflowassignment',
        'targetsubmissionpolicy',
        'dailytargetobligation',
        'dailytargetobligationleader',
        'grouptargetauditlog',
        'alertrule',
        'alertsubscription',
        'alertevent',
        'alertaudience',
        'notificationreceipt',
        'notificationdelivery',
        'alertevaluationrun',
    }

    def _is_local(self, model):
        return model._meta.model_name in self.local_models

    def db_for_read(self, model, **hints):
        """指定模型的读取数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            if self._is_local(model):
                return 'iwork_local'
            if settings.IWORK_PROCESS_ROLE == 'web':
                raise RemoteDatabaseAccessDenied(
                    'Web 进程禁止访问远程生产数据库 iwork'
                )
            return 'iwork'
        return 'default'

    def db_for_write(self, model, **hints):
        """指定模型的写入数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            if self._is_local(model):
                return 'iwork_local'
            return None  # 远程数据库只读
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """判断两个对象是否允许关联"""
        db1 = obj1._state.db
        db2 = obj2._state.db
        if db1 and db2:
            return db1 == db2
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """判断是否允许迁移"""
        if app_label in self.iwork_app_labels:
            if model_name in self.local_models:
                return db == 'iwork_local'
            return False
        return db == 'default'
