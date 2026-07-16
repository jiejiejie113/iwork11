from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from iwork.history_store import snapshot_history_date


class Command(BaseCommand):
    help = '将远程生产数据聚合为本地只读历史快照'

    def add_arguments(self, parser):
        parser.add_argument('--date', dest='target_date', help='单个日期，格式 YYYY-MM-DD')
        parser.add_argument('--start', help='回填开始日期，格式 YYYY-MM-DD')
        parser.add_argument('--end', help='回填结束日期，格式 YYYY-MM-DD')
        parser.add_argument(
            '--continue-on-error',
            action='store_true',
            help='日期范围回填时记录失败并继续后续日期',
        )

    def handle(self, *args, **options):
        dates = self._parse_dates(options)
        failures = []
        for target_date in dates:
            self.stdout.write(f'正在生成 {target_date} 历史快照...')
            try:
                state = snapshot_history_date(target_date)
            except Exception as exc:
                failures.append((target_date, exc))
                self.stderr.write(self.style.ERROR(f'{target_date} 失败: {exc}'))
                if not options['continue_on_error']:
                    raise CommandError(f'{target_date} 历史快照失败') from exc
                continue
            self.stdout.write(self.style.SUCCESS(
                f'{target_date} 完成: 源记录 {state.source_row_count}, '
                f'事实行 {state.fact_row_count}, 元数据 {state.metadata_row_count}, '
                f'版本 v{state.snapshot_version}'
            ))
        if failures:
            raise CommandError(f'{len(failures)} 个日期生成失败')

    @staticmethod
    def _parse_dates(options) -> list[date]:
        target_date = options.get('target_date')
        start = options.get('start')
        end = options.get('end')
        if target_date and (start or end):
            raise CommandError('--date 不能与 --start/--end 同时使用')
        try:
            if target_date:
                return [date.fromisoformat(target_date)]
            if start and end:
                first = date.fromisoformat(start)
                last = date.fromisoformat(end)
                if first > last:
                    raise CommandError('--start 不能晚于 --end')
                return [
                    first + timedelta(days=offset)
                    for offset in range((last - first).days + 1)
                ]
        except ValueError as exc:
            raise CommandError('日期格式必须为 YYYY-MM-DD') from exc
        raise CommandError('请提供 --date，或同时提供 --start 和 --end')
