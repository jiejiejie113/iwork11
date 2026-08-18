"""可信反向代理身份解析。"""

from dataclasses import asdict, dataclass, field

from django.conf import settings


@dataclass(frozen=True, slots=True)
class IworkIdentity:
    """表示由可信代理断言的 iwork 请求身份。"""

    subject: str = ''
    username: str = ''
    email: str = ''
    display_name: str = ''
    keycloak_groups: list[str] = field(default_factory=list)
    is_admin: bool = False

    @property
    def is_authenticated(self) -> bool:
        """判断身份是否具备稳定的 Keycloak subject。

        Returns:
            bool: 具备稳定subject时返回 ``True``。
        """
        return bool(self.subject)

    def as_dict(self) -> dict[str, object]:
        """返回可序列化的身份字典。

        Returns:
            dict[str, object]: 当前身份的全部可序列化字段。
        """
        return asdict(self)


ANONYMOUS_IDENTITY = IworkIdentity()


def parse_trusted_proxy_identity(meta: dict[str, object]) -> IworkIdentity:
    """从已经过可信来源校验的 WSGI 元数据解析身份。

    Args:
        meta (dict[str, object]): Django 请求的 ``META`` 字典。

    Returns:
        IworkIdentity: 完整身份；未携带 subject 时返回匿名身份。
    """
    subject = str(meta.get('HTTP_REMOTE_SUBJECT', '') or '').strip()
    if not subject:
        return ANONYMOUS_IDENTITY

    raw_groups = str(meta.get('HTTP_REMOTE_GROUPS', '') or '')
    groups = [group.strip() for group in raw_groups.split(',') if group.strip()]
    admin_groups = set(getattr(settings, 'IWORK_ADMIN_GROUPS', ['/admin']))
    return IworkIdentity(
        subject=subject,
        username=str(meta.get('HTTP_REMOTE_USER', '') or '').strip(),
        email=str(meta.get('HTTP_REMOTE_EMAIL', '') or '').strip(),
        display_name=str(
            meta.get('HTTP_REMOTE_NAME', '')
            or meta.get('HTTP_REMOTE_DISPLAY_NAME', '')
            or ''
        ).strip(),
        keycloak_groups=groups,
        is_admin=bool(admin_groups.intersection(groups)),
    )
