"""
本地数据相关API视图
"""
import time

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from datetime import date
from loguru import logger

from iwork.statistics import get_local_date_stats, get_date_stats
from iwork.local_queries import get_available_dates
from iwork.request_params import parse_stepno_filter
from iwork.sync import sync_date_data


def _parse_stepno(request) -> list[int] | None:
    """从请求参数解析 StepNo 过滤列表，无参数返回 None（全工序）"""
    return parse_stepno_filter(request)


@api_view(['GET'])
def local_date_stats(request, target_date):
    """获取指定日期的全量统计数据（与实时视图字段完全一致）"""
    try:
        date_obj = date.fromisoformat(target_date)
        mode = request.query_params.get('mode', 'local')
        stepno_filter = _parse_stepno(request)

        if mode == 'local':
            stats = get_local_date_stats(date_obj, stepno_filter=stepno_filter)
            source = 'local'
        else:
            stats = get_date_stats(date_obj, stepno_filter=stepno_filter)
            source = 'remote'

        return Response({
            'date': date_obj.isoformat(),
            'source': source,
            'total_qty': stats['total_qty'],
            'workorder_count': stats['workorder_count'],
            'hourly_stats': stats['hourly_stats'],
            'station_stats': stats['station_stats'],
            'workorders': stats['workorders'],
            'process_flow_stats': stats['process_flow_stats'],
            'monthly_process_stats': stats['monthly_process_stats'],
            'monthly_total_trend': stats['monthly_total_trend'],
            'heatmap_matrix': stats['heatmap_matrix'],
            'station_ranking': stats['station_ranking'],
            'process_stats': stats['top_processes'],
            'top_processes': stats['top_processes'],
            'all_stepnos': stats.get('all_stepnos', []),
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取日期统计失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def available_dates(request):
    """获取可用的日期列表"""
    try:
        mode = request.query_params.get('mode', 'local')
        dates = get_available_dates(mode)

        return Response({
            'mode': mode,
            'dates': [d.isoformat() for d in dates],
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取可用日期失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def sync_date(request, target_date):
    """同步指定日期的数据到本地"""
    t0 = time.time()
    try:
        date_obj = date.fromisoformat(target_date)
        result = sync_date_data(date_obj)
        elapsed = time.time() - t0
        logger.success('POST /api/history/sync/{} 完成 ({:.1f}s) 新增{} 更新{} 跳过{}',
                       target_date, elapsed, result['synced_count'], result['updated_count'], result['skipped_count'])
        return Response({
            'success': True,
            'message': '同步完成',
            'synced_count': result['synced_count'],
            'updated_count': result['updated_count'],
            'skipped_count': result['skipped_count'],
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error('POST /api/history/sync/{} 失败 ({:.0f}ms): {}', target_date, (time.time() - t0) * 1000, e)
        return Response({'error': '同步失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
