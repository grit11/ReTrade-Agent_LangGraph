import hashlib
import json
from datetime import datetime, timezone
from retrade_agent.errors import Conflict, AppError

def now():return datetime.now(timezone.utc).isoformat()

class HumanService:
    def __init__(self,repo,permission):self.repo=repo;self.permission=permission
    async def create(self,session_id,customer_id,request_id,kind,reason,summary,data=None):
        # Stable id means retry/replay cannot create duplicate tickets.
        stable=f'{session_id}|{request_id}|{kind}'
        tid='TK-'+hashlib.sha256(stable.encode()).hexdigest()[:20]
        return await self.repo.create_ticket({'ticket_id':tid,'session_id':session_id,
            'customer_id':customer_id,'request_id':request_id,'kind':kind,'reason':reason[:500],
            'summary':summary[:4000],'status':'pending','assigned_to':None,
            'data':data or {},'created_at':now(),'updated_at':now()})
    async def claim(self,actor,ticket_id,version):
        self.permission.require_staff(actor)
        t=await self.repo.get_ticket(ticket_id)
        if t['status'] not in ('pending','claimed'):raise Conflict('工单当前不能认领')
        if t.get('assigned_to') and t['assigned_to']!=actor.customer_id:raise Conflict('工单已由其他客服认领')
        return await self.repo.save_ticket(ticket_id,{'assigned_to':actor.customer_id,'status':'claimed'},version)
    async def prepare_decision(self,actor,ticket_id,decision,message,expected_version):
        self.permission.require_staff(actor);t=await self.repo.get_ticket(ticket_id)
        allowed={'approve','reject'} if t['kind']=='approval' else {'resolve'}
        if decision not in allowed:raise AppError('该工单不支持此处理动作')
        if not message.strip():raise AppError('请填写给用户的处理说明')
        payload={'decision':decision,'message':message.strip(),'staff_id':actor.customer_id}
        if t['status']=='resolved':
            if t.get('decision')!=payload:raise Conflict('工单已完成，不能改写处理结论')
            return t
        if t['status']=='resolving':
            if t.get('decision')!=payload:raise Conflict('工单正在执行另一个处理结论')
            return t
        if t.get('assigned_to') and t['assigned_to']!=actor.customer_id:raise Conflict('工单已由其他客服认领')
        return await self.repo.save_ticket(ticket_id,{'status':'resolving','assigned_to':actor.customer_id,
                        'decision':payload},expected_version)
    async def complete(self,ticket_id,receipt):
        t=await self.repo.get_ticket(ticket_id)
        if t['status']=='resolved':return t
        return await self.repo.save_ticket(ticket_id,{'status':'resolved','receipt':receipt},t['version'])
