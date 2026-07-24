"""
本地数据相关API视图
"""
import time

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from datetime import date
from loguru import logger

from iwork.statistics import get_business_date, get_local_date_stats
from iwork.local_queries import get_available_dates
from iwork.request_params import parse_stepno_filter
from iwork.history_store import SnapshotBuildInProgressError, snapshot_history_date
from iwork.local_models import HistoricalSyncState


def _parse_stepno(request) -> list[int] | None:
    """从请求参数解析 StepNo 过滤列表，无参数返回 None（全工序）"""
    return parse_stepno_filter(request)


def _snapshot_state(target_date):
    """获取指定日期已成功发布的历史快照状态。"""
    return HistoricalSyncState.objects.using('iwork_local').filter(
        snapshot_date=target_date,
        status=HistoricalSyncState.Status.SUCCESS,
    ).first()


def _parse_target_date(value):
    """解析 ISO 日期并在失败时返回 HTTP 400 响应。"""
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, Response(
            {'error': '日期格式错误，需为 YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(['GET'])
def local_date_stats(request, target_date):
    """从已发布的本地快照获取指定历史日期的全量统计。"""
    date_obj, error_response = _parse_target_date(target_date)
    if error_response:
        return error_response
    try:
        stepno_filter = _parse_stepno(request)
        snapshot = _snapshot_state(date_obj)
        if snapshot is None:
            return Response(
                {'error': '该日期尚未生成本地历史快照', 'code': 'history_snapshot_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        stats = get_local_date_stats(date_obj, stepno_filter=stepno_filter)

        return Response({
            'date': date_obj.isoformat(),
            'source': 'local_snapshot',
            'snapshot_date': date_obj.isoformat(),
            'snapshot_version': snapshot.snapshot_version,
            'snapshot_completed_at': (
                snapshot.completed_at.isoformat() if snapshot.completed_at else None
            ),
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
        dates = get_available_dates('local')

        return Response({
            'source': 'local_snapshot',
            'dates': [d.isoformat() for d in dates],
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取可用日期失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _snapshot_payload(state):
    """将历史快照状态转换为面向客户端的字典。"""
    return {
        'date': state.snapshot_date.isoformat(),
        'version': state.snapshot_version,
        'source_row_count': state.source_row_count,
        'source_total_qty': state.source_total_qty,
        'fact_row_count': state.fact_row_count,
        'metadata_row_count': state.metadata_row_count,
        'missing_metadata_count': state.missing_metadata_count,
        'completed_at': state.completed_at.isoformat() if state.completed_at else None,
    }


@api_view(['POST'])
def ensure_snapshot(request, target_date):
    """确保指定历史日期已有可读取的本地快照。"""
    t0 = time.time()
    date_obj, error_response = _parse_target_date(target_date)
    if error_response:
        return error_response

    if date_obj >= get_business_date():
        return Response(
            {'error': '只能构建已经结束的历史日期'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    existing = _snapshot_state(date_obj)
    if existing:
        return Response({
            'created': False,
            'message': '本地历史快照已存在',
            'snapshot': _snapshot_payload(existing),
        }, status=status.HTTP_200_OK)

    try:
        result = snapshot_history_date(date_obj)
        elapsed = time.time() - t0
        logger.success(
            'POST /api/history/snapshots/{}/ensure 完成 ({:.1f}s) 源记录{} 事实行{} 缺失元数据{}',
            target_date,
            elapsed,
            result.source_row_count,
            result.fact_row_count,
            result.missing_metadata_count,
        )
        return Response({
            'created': True,
            'message': '本地历史快照构建完成',
            'snapshot': _snapshot_payload(result),
        }, status=status.HTTP_201_CREATED)

    except SnapshotBuildInProgressError:
        return Response({
            'created': False,
            'code': 'history_snapshot_building',
            'message': '本地历史快照正在构建',
            'retry_after': 2,
        }, status=status.HTTP_202_ACCEPTED)
    except Exception as e:
        logger.error(
            'POST /api/history/snapshots/{}/ensure 失败 ({:.0f}ms): {}',
            target_date,
            (time.time() - t0) * 1000,
            e,
        )
        return Response({'error': '历史快照构建失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
