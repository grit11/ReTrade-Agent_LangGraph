"""Bounded retries only for idempotent reads/inference, never arbitrary money actions."""
import asyncio
import random
import httpx

async def request_json(client:httpx.AsyncClient,url:str,key:str,payload:dict,attempts:int=3):
    for attempt in range(attempts):
        try:
            response=await client.post(url,headers={'Authorization':f'Bearer {key}'},json=payload)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException,httpx.TransportError,httpx.HTTPStatusError) as exc:
            retryable=not isinstance(exc,httpx.HTTPStatusError) or exc.response.status_code==429 or exc.response.status_code>=500
            if not retryable or attempt==attempts-1:raise
            await asyncio.sleep(min(0.3*2**attempt,2)+random.random()*0.1)
    raise RuntimeError('unreachable')
