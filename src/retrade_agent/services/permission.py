from retrade_agent.errors import Forbidden
from retrade_agent.models import Actor

class PermissionService:
    """Ownership always checked, even with local demo identities."""
    def require_owner(self,actor:Actor,customer_id:str):
        if actor.role!='staff' and actor.customer_id!=customer_id:
            raise Forbidden('无权访问该资源')
    def require_staff(self,actor:Actor):
        if actor.role!='staff':raise Forbidden('需要人工客服权限')
