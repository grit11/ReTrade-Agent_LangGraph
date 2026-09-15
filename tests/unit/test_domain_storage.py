import asyncio
import sqlite3
from datetime import datetime,timezone,timedelta
import pytest
from retrade_agent.models import Actor
from retrade_agent.errors import AppError,Conflict,Forbidden,NotFound
from retrade_agent.api.auth import sign_actor,verify_actor
from retrade_agent.storage.cache import LocalCache

A=Actor('demo-customer');B=Actor('demo-other');STAFF=Actor('staff-local','staff')

async def test_order_ownership(orders):
    values=await orders.list_orders(A)
    assert values and all(o['customer_id']==A.customer_id for o in values)
    with pytest.raises(NotFound):await orders.get_order(A,'202609140004')
    with pytest.raises(NotFound):await orders.get_order(A,'999999999999')
    with pytest.raises(AppError):await orders.get_order(A,"x' OR 1=1")
async def test_payment_logistics(orders):
    o=await orders.get_payment(A,'202608090001');assert o['simulated'] and o['amount_cents']>0
    l=await orders.get_logistics(A,'202608090001');assert isinstance(l['events'],list)
async def test_session_ownership(permission):
    permission.require_owner(A,A.customer_id)
    with pytest.raises(Forbidden):permission.require_owner(A,B.customer_id)
    with pytest.raises(Forbidden):permission.require_staff(A)
def test_signed_identity():
    token=sign_actor(A,'test-secret')
    assert verify_actor(token,'test-secret')==A
    with pytest.raises(AppError):verify_actor(token+'a','test-secret')
    with pytest.raises(AppError):verify_actor(sign_actor(A,'test-secret',ttl=-1),'test-secret')
    with pytest.raises(AppError):verify_actor('bad','test-secret')
async def test_request_idempotency(repo):
    x=await repo.begin_run('rid','sid','fingerprint')
    assert x['status']=='processing'
    await repo.finish_run('rid',{'reply':'ok'})
    x=await repo.begin_run('rid','sid','fingerprint');assert x['response']['reply']=='ok'
    with pytest.raises(Conflict):await repo.begin_run('rid','sid','other')
    with pytest.raises(Conflict):await repo.begin_run('rid','other-session','fingerprint')
async def test_message_dedup_and_restart(repo):
    await repo.create_session('sid',A.customer_id)
    await repo.add_message('sid','m1','user','问题')
    await repo.add_message('sid','m1','user','问题')
    from retrade_agent.storage.sqlite import SqliteRepository
    restarted=SqliteRepository(repo.path)
    assert len(await restarted.messages('sid'))==1
    assert (await restarted.get_session('sid'))['customer_id']==A.customer_id
async def test_session_lease_conflict_and_release(repo):
    async with repo.lease('sid'):
        with pytest.raises(Conflict):
            async with repo.lease('sid'):pass
        async with repo.lease('other'):pass
    async with repo.lease('sid'):pass
async def test_operation_no_duplicate(repo):
    a=await repo.operation('key','fp',{'id':1})
    b=await repo.operation('key','fp',{'id':2})
    assert a==b=={'id':1}
    with pytest.raises(Conflict):await repo.operation('key','new-fp',{'id':1})
async def test_ticket_idempotent_and_optimistic_lock(human,repo):
    t=await human.create('sid',A.customer_id,'rid','support','reason','summary')
    same=await human.create('sid',A.customer_id,'rid','support','reason','summary')
    assert t['ticket_id']==same['ticket_id']
    updated=await human.claim(STAFF,t['ticket_id'],t['version'])
    assert updated['status']=='claimed'
    with pytest.raises(Conflict):await human.claim(STAFF,t['ticket_id'],t['version'])
async def test_human_decision_auth_types_and_replay(human):
    t=await human.create('sid',A.customer_id,'rid','support','reason','summary')
    with pytest.raises(Forbidden):await human.prepare_decision(A,t['ticket_id'],'resolve','ok',t['version'])
    with pytest.raises(AppError):await human.prepare_decision(STAFF,t['ticket_id'],'approve','ok',t['version'])
    r=await human.prepare_decision(STAFF,t['ticket_id'],'resolve','人工结果',t['version'])
    assert r['status']=='resolving'
    again=await human.prepare_decision(STAFF,t['ticket_id'],'resolve','人工结果',t['version'])
    assert again['decision']==r['decision']
    with pytest.raises(Conflict):await human.prepare_decision(STAFF,t['ticket_id'],'resolve','另一个结论',t['version'])
    await human.complete(t['ticket_id'],{'reply':'done'})
    r=await human.prepare_decision(STAFF,t['ticket_id'],'resolve','人工结果',t['version']);assert r['receipt']['reply']=='done'

def case(order_id='202609140001',**fields):
    return {'case_id':'CS-testcase0000000001','session_id':'sid','customer_id':A.customer_id,
            'order_id':order_id,'issue_type':'return','reason':'不想要','unused':True,
            'customer_confirmed':True,**fields}
async def test_policy_low_risk(after_sales,orders):
    o=await orders.get_order(A,'202609140001');d=after_sales.evaluate(o,case())
    assert d.eligible and d.risk=='low' and not d.requires_manual
async def test_policy_high_amount(after_sales,orders):
    o=await orders.get_order(A,'202609140002');d=after_sales.evaluate(o,case(o['order_id']))
    assert d.eligible and d.requires_manual
async def test_policy_expired(after_sales,orders):
    o=await orders.get_order(A,'202609140003');assert not after_sales.evaluate(o,case(o['order_id'])).eligible
@pytest.mark.parametrize('issue',['damaged','not_as_described'])
async def test_dispute_requires_review(after_sales,orders,issue):
    o=await orders.get_order(A,'202609140001');assert after_sales.evaluate(o,case(issue_type=issue)).requires_manual
async def test_used_goods_requires_review(after_sales,orders):
    o=await orders.get_order(A,'202609140001');assert after_sales.evaluate(o,case(unused=False)).requires_manual
async def test_unpaid_rejected(after_sales,orders):
    o=await orders.get_order(A,'202609140001');o['payment_status']='unpaid';assert not after_sales.evaluate(o,case()).eligible
async def test_confirmation_required(after_sales):
    with pytest.raises(Conflict):await after_sales.apply(A,case(customer_confirmed=False))
async def test_mock_apply_idempotent(after_sales,repo):
    result=await after_sales.apply(A,case());repeat=await after_sales.apply(A,case())
    assert result['result']==repeat['result'] and result['result']['simulated']
    assert (await repo.get_case(case()['case_id']))['status']=='completed'
async def test_manual_approval_fingerprint(after_sales,orders,human,repo):
    cs=case('202609140002');order=await orders.get_order(A,cs['order_id'])
    fp=after_sales.action_fingerprint(cs,order)
    t=await human.create('sid',A.customer_id,cs['case_id'],'approval','high','summary',{'action_fingerprint':fp})
    cs['ticket_id']=t['ticket_id']
    with pytest.raises(Forbidden):await after_sales.apply(A,cs)
    await human.prepare_decision(STAFF,t['ticket_id'],'approve','已审核',t['version'])
    changed={**cs,'issue_type':'refund'}
    with pytest.raises(Conflict):await after_sales.apply(A,changed)
    done=await after_sales.apply(A,cs);assert done['result']['simulated']
async def test_cache_ttl_and_ratelimit():
    c=LocalCache();await c.put('k',{'reply':'public'},1)
    assert (await c.get('k'))['reply']=='public'
    assert await c.allow('u',2) and await c.allow('u',2)
    assert not await c.allow('u',2)
    assert await c.allow('other',2)
    await asyncio.sleep(1.05);assert await c.get('k') is None
    await c.close()
