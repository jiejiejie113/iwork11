from django.db import migrations, models


class CreateModelIfMissing(migrations.CreateModel):
    """创建模型表，但兼容服务器已由同步任务预创建该表。"""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """目标表不存在时执行正向建表。

        Args:
            app_label: 当前迁移所属的 Django 应用标签。
            schema_editor: 当前数据库连接对应的结构编辑器。
            from_state: 执行迁移前的项目状态。
            to_state: 执行迁移后的项目状态。
        """
        model = to_state.apps.get_model(app_label, self.name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        with schema_editor.connection.cursor() as cursor:
            tables = schema_editor.connection.introspection.table_names(cursor)
        if model._meta.db_table not in tables:
            schema_editor.create_model(model)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        """反向迁移时保留由服务器同步任务维护的实际快照表。

        Args:
            app_label: 当前迁移所属的 Django 应用标签。
            schema_editor: 当前数据库连接对应的结构编辑器。
            from_state: 执行反向迁移前的项目状态。
            to_state: 执行反向迁移后的项目状态。
        """
        return


class Migration(migrations.Migration):
    """登记服务器同步任务生成的 iGarment 精简快照表。"""

    dependencies = [
        ('iwork', '0006_grouptargetproduction_planned_work_minutes'),
    ]

    operations = [
        CreateModelIfMissing(
            name='IGarmentProductionOrder',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'customer_order_no',
                    models.CharField(
                        blank=True,
                        default='',
                        max_length=20,
                        verbose_name='客户订单编号',
                    ),
                ),
                (
                    'order_no',
                    models.CharField(max_length=50, verbose_name='订单编号'),
                ),
                ('quantity', models.IntegerField(verbose_name='订单数量')),
                ('created_date', models.DateTimeField(verbose_name='创建日期')),
            ],
            options={
                'verbose_name': 'iGarment 生产订单',
                'verbose_name_plural': 'iGarment 生产订单',
                'db_table': 'igarment_production_orders',
                'managed': True,
                'indexes': [
                    models.Index(
                        fields=['customer_order_no', 'created_date'],
                        name='idx_igarment_customer_created',
                    ),
                    models.Index(
                        fields=['order_no'],
                        name='idx_igarment_order_no',
                    ),
                ],
            },
        ),
    ]
