from django.db import migrations, models


class Migration(migrations.Migration):
    """登记远程初版款号模型，并扩展历史工序元数据快照。"""

    dependencies = [
        ('iwork', '0007_igarmentproductionorder'),
    ]

    operations = [
        migrations.CreateModel(
            name='Pywrkord',
            fields=[
                (
                    'WrkOrder',
                    models.CharField(
                        max_length=14,
                        primary_key=True,
                        serialize=False,
                        verbose_name='完整工单号',
                    ),
                ),
                (
                    'ExtField01',
                    models.CharField(
                        blank=True,
                        default='',
                        max_length=100,
                        null=True,
                        verbose_name='初版款号',
                    ),
                ),
            ],
            options={
                'verbose_name': '工单扩展信息',
                'verbose_name_plural': '工单扩展信息',
                'db_table': 'pywrkord',
                'managed': False,
            },
        ),
        migrations.AddField(
            model_name='historicalstepsnapshot',
            name='initial_style_no',
            field=models.CharField(
                blank=True,
                default='',
                max_length=100,
                verbose_name='初版款号',
            ),
        ),
    ]
