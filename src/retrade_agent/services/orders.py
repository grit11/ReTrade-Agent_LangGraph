import re
from retrade_agent.errors import NotFound, AppError
from retrade_agent.models import Actor

class OrderService:
    def __init__(self,repo,permission):self.repo=repo;self.permission=permission
    async def list_orders(self,actor:Actor):
        # Runtime identity is authoritative; never expose other customers' order IDs.
        return [o for o in await self.repo.get_orders() if o['customer_id']==actor.customer_id]
    async def get_order(self,actor:Actor,order_id:str):
        if not re.fullmatch(r'[0-9]{6,20}',order_id):raise AppError('订单号应为 6–20 位数字')
        # Not found and not owned have the same public response (no enumeration).
        for o in await self.list_orders(actor):
            if o['order_id']==order_id:return o
        raise NotFound('未找到属于当前账户的订单，请核对订单号')
    async def get_logistics(self,actor:Actor,order_id:str):
        o=await self.get_order(actor,order_id)
        return {'order_id':order_id,'status':o['status'],'events':o['logistics'],'simulated':True}
    async def get_payment(self,actor:Actor,order_id:str):
        o=await self.get_order(actor,order_id)
        return {'order_id':order_id,'payment_status':o['payment_status'],'amount_cents':o['amount_cents'],'simulated':True}
