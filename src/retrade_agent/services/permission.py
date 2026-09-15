"""权限服务模块，封装客户归属和员工身份检查。"""
from retrade_agent.errors import Forbidden
from retrade_agent.models import Actor


class PermissionService:
    """Ownership always checked, even with local demo identities."""

    def require_owner(self, actor: Actor, customer_id: str):
        """校验访问者是否为指定客户本人或员工。"""
        if actor.role != "staff" and actor.customer_id != customer_id:
            raise Forbidden("无权访问该资源")

    def require_staff(self, actor: Actor):
        """校验当前请求是否来自员工身份。"""
        if actor.role != "staff":
            raise Forbidden("需要人工客服权限")
