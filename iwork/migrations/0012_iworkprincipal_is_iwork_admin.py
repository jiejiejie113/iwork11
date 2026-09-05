from django.db import migrations, models


class Migration(migrations.Migration):
    """为 iwork 身份快照增加专属管理员角色字段。"""

    dependencies = [
        ('iwork', '0011_historicalproductionfact_employee_remark'),
    ]

    operations = [
        migrations.AddField(
            model_name='iworkprincipal',
            name='is_iwork_admin',
            field=models.BooleanField(
                default=False,
                verbose_name='是否 iwork 专属管理员',
            ),
        ),
    ]
