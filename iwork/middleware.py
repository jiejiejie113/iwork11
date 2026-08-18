"""
Docker 明确信任代理校验中间件

仅接受配置中明确列出的反向代理主机解析地址。共享Docker网络中的其他
容器即使能够连接应用，也不能自行签发 Remote-* 身份。

安全前提：iwork 仅通过 Nginx 反向代理访问，应用端口不对外暴露。

通过来源校验后，本中间件才会读取 Remote-*，并创建稳定的请求身份对象。
"""
import socket
import time

from django.conf import settings
from django.http import HttpResponse

from iwork.identity import parse_trusted_proxy_identity

# ======
# 可信代理DNS缓存
TRUSTED_PROXY_DNS_CACHE_SECONDS = 30.0
LOCAL_LOOPBACK_ADDRESSES = {'127.0.0.1', '::1'}


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
