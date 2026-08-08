"""为已发布历史快照回填初版款号。"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from loguru import logger

from iwork.local_models import HistoricalStepSnapshot, HistoricalSyncState
from iwork.queries import get_initial_style_numbers


# ======
# 批量查询配置
DEFAULT_BATCH_SIZE = 500


class Command(BaseCommand):
    """按完整本厂款号批量回填已发布历史快照的初版款号。"""

    help = '为成功发布且初版款号为空的历史快照补充 pywrkord.ExtField01'

    def add_arguments(self, parser):
        """注册远程批量查询大小参数。

        Args:
            parser: Django 命令参数解析器。
        """
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f'每次查询远程 pywrkord 的工单数，默认 {DEFAULT_BATCH_SIZE}',
        )

    def handle(self, *args, **options):
        """回填空字段，并按实际变更日期递增快照版本。

        Args:
            *args: Django 管理命令位置参数。
            **options: Django 管理命令选项。

        Raises:
            CommandError: 批量大小不是正整数。
        """
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size 必须大于或等于 1')

        successful_dates = HistoricalSyncState.objects.using('iwork_local').filter(
            status=HistoricalSyncState.Status.SUCCESS,
        ).values('snapshot_date')
        wrk_orders = list(
            HistoricalStepSnapshot.objects.using('iwork_local')
            .filter(
                snapshot_date__in=successful_dates,
                initial_style_no='',
            )
            .exclude(wrk_order='')
            .order_by('wrk_order')
            .values_list('wrk_order', flat=True)
            .distinct()
        )
        if not wrk_orders:
            logger.success('历史初版款号无需回填')
            self.stdout.write(self.style.SUCCESS('历史初版款号无需回填'))
            return

        mappings = {}
        for offset in range(0, len(wrk_orders), batch_size):
            batch = wrk_orders[offset:offset + batch_size]
            mappings.update(get_initial_style_numbers(batch))

        available = {
            wrk_order: str(mappings.get(wrk_order) or '').strip()
            for wrk_order in wrk_orders
            if str(mappings.get(wrk_order) or '').strip()
        }
        missing = sorted(set(wrk_orders) - set(available))
        if missing:
            logger.warning(
                '有 {} 个本厂款号未匹配初版款号，保留空值: {}',
                len(missing),
                ', '.join(missing),
            )

        changed_rows = 0
        changed_dates = 0
        if available:
            target_dates = list(
                HistoricalStepSnapshot.objects.using('iwork_local')
                .filter(
                    snapshot_date__in=successful_dates,
                    initial_style_no='',
                    wrk_order__in=available,
                )
                .order_by('snapshot_date')
                .values_list('snapshot_date', flat=True)
                .distinct()
            )
            for target_date in target_dates:
                updated = self._backfill_date(target_date, available)
                if updated:
                    changed_rows += updated
                    changed_dates += 1

        message = (
            f'历史初版款号回填完成：更新 {changed_rows} 行，'
            f'影响 {changed_dates} 个日期，未匹配 {len(missing)} 个本厂款号'
        )
        logger.success(message)
        self.stdout.write(self.style.SUCCESS(message))

    @staticmethod
    def _backfill_date(target_date, mappings: dict[str, str]) -> int:
        """在单个本地事务内更新一个成功快照日期。

        Args:
            target_date: 待回填的历史快照日期。
            mappings: 按完整本厂款号组织的非空初版款号映射。

        Returns:
            int: 实际更新的元数据行数。
        """
        with transaction.atomic(using='iwork_local'):
            state = (
                HistoricalSyncState.objects.using('iwork_local')
                .select_for_update()
                .filter(
                    snapshot_date=target_date,
                    status=HistoricalSyncState.Status.SUCCESS,
                )
                .first()
            )
            if state is None:
                logger.warning('{} 不是成功快照，跳过初版款号回填', target_date)
                return 0

            rows = list(
                HistoricalStepSnapshot.objects.using('iwork_local')
                .select_for_update()
                .filter(
                    snapshot_date=target_date,
                    initial_style_no='',
                    wrk_order__in=mappings,
                )
            )
            for row in rows:
                row.initial_style_no = mappings[row.wrk_order]
            if not rows:
                return 0

            HistoricalStepSnapshot.objects.using('iwork_local').bulk_update(
                rows,
                ['initial_style_no'],
                batch_size=DEFAULT_BATCH_SIZE,
            )
            state.snapshot_version += 1
            state.save(using='iwork_local', update_fields=['snapshot_version'])
            return len(rows)
