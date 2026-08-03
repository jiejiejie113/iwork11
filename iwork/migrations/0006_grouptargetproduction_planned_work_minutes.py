from django.db import migrations, models


class Migration(migrations.Migration):
    """为整组目标增加可选的计划工作时长。"""

    dependencies = [
        ('iwork', '0005_grouptargetproduction'),
    ]

    operations = [
        migrations.AddField(
            model_name='grouptargetproduction',
            name='planned_work_minutes',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name='计划工作分钟',
            ),
        ),
    ]
