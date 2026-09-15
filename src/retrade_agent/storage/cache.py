"""只缓存公开答案；Redis 为可选依赖，故障时按缓存未命中降级。"""
import asyncio
import json
import time
from collections import defaultdict, deque


class LocalCache:
    """本地内存缓存与限流实现，适用于无 Redis 的开发环境。"""

    backend = "local"

    def __init__(self):
        """初始化实例依赖和内部状态。"""
        self.values = {}
        self.windows = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def get(self, key):
        """读取指定键的缓存或仓库记录。"""
        item = self.values.get(key)
        if item and item[0] > time.monotonic():
            return json.loads(item[1])
        self.values.pop(key, None)
        return None

    async def put(self, key, value, ttl):
        """写入指定键的缓存或仓库记录。"""
        if len(self.values) > 1000:
            self.values = {k: v for k, v in self.values.items() if v[0] > time.monotonic()}
            if len(self.values) > 1000:
                self.values.pop(next(iter(self.values)))
        self.values[key] = (time.monotonic() + ttl, json.dumps(value, ensure_ascii=False))

    async def allow(self, key, limit, window=60):
        """按时间窗口执行限流判断。"""
        async with self.lock:
            now = time.monotonic()
            q = self.windows[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.windows) > 10000:
                self.windows = defaultdict(
                    deque, {k: v for k, v in self.windows.items() if v and v[-1] > now - window}
                )
            return True

    async def close(self):
        """释放客户端或缓存持有的资源。"""
        pass


class RedisCache(LocalCache):
    """Redis 缓存与限流实现，适用于共享运行环境。"""

    backend = "redis"

    def __init__(self, url):
        """初始化实例依赖和内部状态。"""
        super().__init__()
        from redis.asyncio import Redis

        self.client = Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        self.degraded = False

    async def get(self, key):
        """读取指定键的缓存或仓库记录。"""
        try:
            value = await self.client.get("retrade:cache:" + key)
            return json.loads(value) if value else None
        except Exception:
            self.degraded = True
            return None

    async def put(self, key, value, ttl):
        """写入指定键的缓存或仓库记录。"""
        try:
            await self.client.set("retrade:cache:" + key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception:
            self.degraded = True

    async def allow(self, key, limit, window=60):
        """按时间窗口执行限流判断。"""
        script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
        try:
            n = await self.client.eval(script, 1, "retrade:ratelimit:" + key, window)
            return n <= limit
        except Exception:
            self.degraded = True
            return await super().allow(key, limit, window)

    async def close(self):
        """释放客户端或缓存持有的资源。"""
        await self.client.aclose()
