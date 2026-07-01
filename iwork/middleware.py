"""
Docker 内部网络 IP 校验中间件

仅接受来自 Docker 内部网络的请求（bridge 网络默认 172.x，也可包含
10.x, 192.168.x）。这是纵深防御的最后一层——即使 Nginx 的 Remote-*
header 清理被误改，此中间件仍能阻止外部伪造请求到达应用层。

安全前提：iwork 仅通过 Nginx 反向代理访问，应用端口不对外暴露。

注意：此中间件不读取 Remote-User header（iwork 采用"信任 Nginx
认证边界"策略，认证完全由 Nginx + oauth2-proxy 保证）。
"""
from django.http import HttpResponse

# Docker 内部网络 IP 前缀（bridge 默认 172.x，也兼容其他私有网段）
_TRUSTED_IP_PREFIXES = ('172.', '10.', '192.168.', '127.')


class TrustedProxyMiddleware:
    """
    仅允许来自 Docker 内部网络的请求通过

    任何非信任来源的请求直接返回 403 Forbidden。
    本地开发时 127.0.0.1 在信任列表中，不受影响。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        remote_addr = request.META.get('REMOTE_ADDR', '')

        if not remote_addr:
            return HttpResponse(
                'Forbidden: missing client IP',
                status=403,
            )

        if not any(remote_addr.startswith(prefix) for prefix in _TRUSTED_IP_PREFIXES):
            return HttpResponse(
                'Forbidden: untrusted source IP',
                status=403,
            )

        return self.get_response(request)
