"""
本地数据相关API视图
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from datetime import date
from typing import Any
from django.conf import settings
from loguru import logger
from redis.exceptions import LockError

from iwork.statistics import get_business_date, get_local_date_stats
from iwork.local_queries import get_available_dates
from iwork.request_params import parse_stepno_filter
from iwork.local_models import HistoricalSyncState
from iwork.snapshot_request_lock import (
    RequestLockLease,
    acquire_request_lock,
    renew_request_lock,
    snapshot_build_in_progress,
)
from iwork.tasks import build_history_snapshot

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


def _claim_snapshot_request(
    target_date: str,
) -> tuple[Any, str, RequestLockLease | None, bool]:
    """申请单日期历史快照的后台任务入队资格。

    请求锁使用唯一所有权令牌，避免旧任务误删新请求。取得请求锁后继续使用
    Redis 锁原生语义检查真实构建锁；已有构建者时立即释放请求锁并等待轮询。

    Args:
        target_date (str): ISO 格式的目标日期。

    Returns:
        tuple[Any, str, RequestLockLease | None, bool]:
            请求锁、所有权令牌、续租器和是否取得入队资格。
    """
    request_lock, request_token, request_claimed = acquire_request_lock(
        target_date,
        settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT,
    )
    if not request_claimed:
        return request_lock, request_token, None, False

    request_lease = RequestLockLease(
        request_lock,
        settings.HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT,
        settings.HISTORY_SNAPSHOT_REQUEST_RENEW_INTERVAL,
    )
    try:
        request_lease.start()
        if request_lease.lost:
            raise ConnectionError('历史快照请求锁初始续租失败')
        if snapshot_build_in_progress(target_date):
            request_lease.stop()
            try:
                request_lock.release()
            except LockError:
                logger.warning('历史快照请求锁已失效: date={}', target_date)
            return request_lock, request_token, None, False
    except Exception:
        request_lease.stop()
        try:
            request_lock.release()
        except Exception as cleanup_error:
            logger.warning(
                '释放历史快照请求锁失败: date={} error={}',
                target_date,
                cleanup_error,
            )
        raise

    return request_lock, request_token, request_lease, True


@api_view(['POST'])
def ensure_snapshot(request, target_date):
    """确保指定历史日期已有可读取快照，否则仅提交后台任务。"""
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
        (
            request_lock,
            request_token,
            request_lease,
            request_claimed,
        ) = _claim_snapshot_request(target_date)
    except Exception as exc:
        logger.warning('历史快照入队锁暂不可用: date={} error={}', target_date, exc)
        return Response(
            {
                'error': '历史快照任务队列暂不可用，请稍后重试',
                'code': 'history_snapshot_queue_unavailable',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if not request_claimed:
        return Response({
            'created': False,
            'code': 'history_snapshot_building',
            'message': '本地历史快照正在构建',
            'retry_after': 2,
        }, status=status.HTTP_202_ACCEPTED)

    try:
        task = build_history_snapshot.delay(target_date, request_token)
        request_lease.stop()
        if request_lease.lost:
            logger.warning(
                'Broker提交期间历史快照请求锁已失效: date={}',
                target_date,
            )
        if not request_lease.lost:
            try:
                if not renew_request_lock(
                    request_lock,
                    settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT,
                ):
                    logger.warning('历史快照请求锁确认失败: date={}', target_date)
            except Exception as renewal_error:
                logger.warning(
                    '续租历史快照请求锁失败: date={} error={}',
                    target_date,
                    renewal_error,
                )
        logger.info('历史快照 {} 已提交后台任务: {}', target_date, task.id)
        return Response({
            'created': False,
            'code': 'history_snapshot_building',
            'message': '本地历史快照已提交后台构建',
            'retry_after': 2,
        }, status=status.HTTP_202_ACCEPTED)
    except Exception as e:
        request_lease.stop()
        try:
            request_lock.release()
        except Exception as cleanup_error:
            logger.warning(
                '释放历史快照请求锁失败: date={} error={}',
                target_date,
                cleanup_error,
            )
        logger.error(
            'POST /api/history/snapshots/{}/ensure 提交失败: {}',
            target_date,
            e,
        )
        return Response({'error': '历史快照任务提交失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
