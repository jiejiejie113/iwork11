"""
Docker 明确信任代理校验中间件

仅接受配置中明确列出的反向代理主机解析地址。共享Docker网络中的其他
容器即使能够连接应用，也不能自行签发 Remote-* 身份。

安全前提：iwork 仅通过 Nginx 反向代理访问，应用端口不对外暴露。

通过来源校验后，本中间件才会读取 Remote-*，并创建稳定的请求身份对象。
"""
import socket
import time
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from loguru import logger

from iwork.identity import parse_trusted_proxy_identity
# 目标完整性检查只读取 iwork_local，不依赖缓存，作为业务 API 之外的纵深防线。
from iwork.local_models import DailyTargetObligation, ManagedFlowAssignment
from iwork.statistics import get_business_date
from iwork.target_responsibility import (
    LOCAL_DB_ALIAS,
    TARGET_INCOMPLETE_STATUSES,
    active_assignment_query,
    ensure_daily_target_obligations,
)

# ======
# 可信代理DNS缓存
TRUSTED_PROXY_DNS_CACHE_SECONDS = 30.0
LOCAL_LOOPBACK_ADDRESSES = {'127.0.0.1', '::1'}
TARGET_SUBMISSION_REQUIRED_CODE = 'target_submission_required'
TARGET_PAGE_PATH = '/targets/today/'
TARGET_API_PATH = '/api/account/today-targets/'
TARGET_SAVE_API_PATH = '/api/dashboard/set-targets/'
NOTIFICATION_API_PREFIXES = (
    '/api/account/notifications/',
    '/api/account/subscriptions/',
)
HEALTH_PATHS = {'/health', '/health/'}


class TrustedProxyMiddleware:
    """
    仅允许来自明确配置的Docker反向代理或本机回环请求通过。

    任何非信任来源的请求直接返回 403 Forbidden。
    本地开发时 127.0.0.1 在信任列表中，不受影响。
    """

    def __init__(self, get_response):
        """保存后续请求处理器。

        Args:
            get_response (Callable): Django后续请求处理器。
        """
        self.get_response = get_response
        self._trusted_ips = set(LOCAL_LOOPBACK_ADDRESSES)
        self._trusted_ips_expires_at = 0.0

    def _resolve_trusted_ips(self, *, force: bool = False) -> set[str]:
        """解析配置的可信代理主机并短期缓存地址。

        Args:
            force (bool): 是否忽略尚未过期的缓存并重新解析。

        Returns:
            set[str]: 本机回环地址和已解析的可信代理地址。
        """
        now = time.monotonic()
        if not force and now < self._trusted_ips_expires_at:
            return self._trusted_ips
        resolved = set(LOCAL_LOOPBACK_ADDRESSES)
        for hostname in settings.IWORK_TRUSTED_PROXY_HOSTS:
            try:
                resolved.update(
                    item[4][0]
                    for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
                )
            except socket.gaierror:
                continue
        self._trusted_ips = resolved
        self._trusted_ips_expires_at = now + TRUSTED_PROXY_DNS_CACHE_SECONDS
        return resolved

    def __call__(self, request):
        """验证代理来源并挂载可信身份。

        Args:
            request (HttpRequest): 当前Django请求。

        Returns:
            HttpResponse: 拒绝响应或后续处理器响应。
        """
        remote_addr = request.META.get('REMOTE_ADDR', '')

        if not remote_addr:
            return HttpResponse(
                'Forbidden: missing client IP',
                status=403,
            )

        trusted_ips = LOCAL_LOOPBACK_ADDRESSES
        if remote_addr not in trusted_ips:
            trusted_ips = self._resolve_trusted_ips()
            if remote_addr not in trusted_ips:
                trusted_ips = self._resolve_trusted_ips(force=True)
        if remote_addr not in trusted_ips:
            return HttpResponse(
                'Forbidden: untrusted source IP',
                status=403,
            )

        request.iwork_identity = parse_trusted_proxy_identity(request.META)
        return self.get_response(request)


def _path_variants(request) -> set[str]:
    """返回同时兼容应用内路径和 ``/iwork/`` 外部路径的请求路径。

    Args:
        request (HttpRequest): 当前 Django 请求。

    Returns:
        set[str]: 去除尾部斜杠差异后的路径集合。
    """
    variants = set()
    for attribute in ('path_info', 'path'):
        value = str(getattr(request, attribute, '') or '')
        if not value:
            continue
        variants.add(value)
        if value.startswith('/iwork/'):
            variants.add(value[len('/iwork'):])
    return variants


def _is_same_path(path: str, expected: str) -> bool:
    """判断路径是否与指定端点相同，忽略末尾斜杠差异。

    Args:
        path (str): 待判断路径。
        expected (str): 期望路径。

    Returns:
        bool: 路径相同时返回 ``True``。
    """
    return path.rstrip('/') == expected.rstrip('/')


def _is_child_path(path: str, prefix: str) -> bool:
    """判断路径是否为某个 API 前缀或其子路径。

    Args:
        path (str): 待判断路径。
        prefix (str): API 前缀。

    Returns:
        bool: 路径命中前缀时返回 ``True``。
    """
    normalized_prefix = prefix.rstrip('/')
    return path == normalized_prefix or path.startswith(normalized_prefix + '/')


def _public_iwork_prefix() -> str:
    """根据 ``STATIC_URL`` 推导浏览器可访问的 iwork 公共前缀。

    Returns:
        str: 以斜杠结尾的公共前缀，例如 ``/iwork/`` 或 ``/``。
    """
    static_path = urlsplit(str(getattr(settings, 'STATIC_URL', '/static/'))).path
    marker = '/static/'
    marker_index = static_path.rfind(marker)
    if marker_index >= 0:
        prefix = static_path[:marker_index + 1]
        return prefix or '/'
    return '/'


def _safe_internal_path(value: str) -> str:
    """校验门禁保存的返回地址，防止构造开放重定向。

    Args:
        value (str): 当前请求的完整站内路径。

    Returns:
        str: 合法站内路径；不合法时返回根路径。
    """
    parsed = urlsplit(value)
    if (
        not value
        or '\\' in value
        or parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith('/')
        or parsed.path.startswith('//')
    ):
        return '/'
    return value


def _is_gate_exempt(request) -> bool:
    """判断静态文件、目标页面、目标接口、通知接口或健康请求是否放行。

    Args:
        request (HttpRequest): 当前 Django 请求。

    Returns:
        bool: 应绕过目标提交门禁时返回 ``True``。
    """
    paths = _path_variants(request)
    static_path = urlsplit(str(getattr(settings, 'STATIC_URL', '/static/'))).path.rstrip('/')
    for path in paths:
        if path.startswith('/static/') or (
            static_path and path.startswith(static_path + '/')
        ):
            return True
        if _is_same_path(path, TARGET_PAGE_PATH):
            return True
        if _is_same_path(path, TARGET_API_PATH) or _is_same_path(path, TARGET_SAVE_API_PATH):
            return True
        if any(_is_child_path(path, prefix) for prefix in NOTIFICATION_API_PREFIXES):
            return True
        if any(_is_same_path(path, health_path) for health_path in HEALTH_PATHS):
            return True
    return False


def _has_unfinished_target_submission(identity) -> bool:
    """从 ``iwork_local`` 判断当前负责人是否存在未完成的今日责任。

    Args:
        identity (IworkIdentity): 当前可信代理身份。

    Returns:
        bool: 存在待提交或已逾期责任时返回 ``True``。
    """
    business_date = get_business_date()
    flow_names = set(
        ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS)
        .filter(
            active_assignment_query(business_date),
            principal__subject=identity.subject,
            flow_name__in=settings.VISIBLE_FLOWS,
        )
        .values_list('flow_name', flat=True)
    )
    if not flow_names:
        return False
    ensure_daily_target_obligations(business_date)
    return DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).filter(
        target_date=business_date,
        flow_name__in=flow_names,
        status__in=TARGET_INCOMPLETE_STATUSES,
    ).exists()


class TargetSubmissionGateMiddleware:
    """强制要求当前有效负责人先完成今日目标提交。

    该门禁位于可信身份解析之后，使用本地责任库实时核验；普通页面重定向
    到今日目标页，业务 API 则返回稳定的 403 错误码。责任判断异常时对已
    认证请求返回 503，避免依赖故障被误判为已完成。
    """

    def __init__(self, get_response):
        """保存后续请求处理器。

        Args:
            get_response (Callable): Django 后续请求处理器。
        """
        self.get_response = get_response

    def __call__(self, request):
        """执行目标提交门禁并处理放行、重定向或 API 错误响应。

        Args:
            request (HttpRequest): 当前 Django 请求。

        Returns:
            HttpResponse: 后续响应、今日目标重定向或门禁错误响应。
        """
        identity = getattr(request, 'iwork_identity', None)
        if identity is None or not identity.subject:
            return self.get_response(request)
        if identity.is_admin or _is_gate_exempt(request):
            return self.get_response(request)

        try:
            required = _has_unfinished_target_submission(identity)
        except Exception as exc:
            logger.exception('今日目标门禁核验失败: subject={} error={}', identity.subject, exc)
            return JsonResponse(
                {
                    'error': '今日目标状态暂时无法确认，请稍后重试',
                    'code': 'target_submission_check_unavailable',
                },
                status=503,
            )
        if not required:
            return self.get_response(request)

        paths = _path_variants(request)
        is_api_request = any(path.startswith('/api/') for path in paths)
        if is_api_request:
            return JsonResponse(
                {
                    'error': '请先完成今日目标填写后再使用 iwork',
                    'code': TARGET_SUBMISSION_REQUIRED_CODE,
                },
                status=403,
            )

        return_path = _safe_internal_path(request.get_full_path())
        query = urlencode({'next': return_path})
        location = f'{_public_iwork_prefix()}{TARGET_PAGE_PATH.lstrip("/")}?{query}'
        return HttpResponseRedirect(location)
