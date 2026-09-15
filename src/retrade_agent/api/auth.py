"""Local demo identities use signed tokens. Replace authenticate() with your IdP later.
Never accept customer_id from tool arguments or from a chat request body.
"""
import base64
import hashlib
import hmac
import json
import time
from fastapi import Request
from retrade_agent.errors import Unauthorized
from retrade_agent.models import Actor


def sign_actor(actor: Actor, secret: str, ttl=28800):
    """使用 HMAC 为访问者签发带过期时间的令牌。"""
    payload = json.dumps(
        {"sub": actor.customer_id, "role": actor.role, "exp": int(time.time()) + ttl}, separators=(",", ":")
    ).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig


def verify_actor(token: str, secret: str):
    """校验令牌签名、过期时间并恢复访问者身份。"""
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if value["exp"] < time.time() or value["role"] not in ("customer", "staff"):
            raise ValueError()
        return Actor(value["sub"], value["role"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise Unauthorized("登录状态无效或已过期") from exc


async def authenticate(request: Request) -> Actor:
    """从 Authorization 头中解析并校验当前访问者。"""
    c = request.app.state.container
    admin = request.headers.get("X-Admin-Token")
    if admin:
        if not hmac.compare_digest(admin, c.settings.admin_api_key.get_secret_value()):
            raise Unauthorized("客服管理密钥错误")
        return Actor("staff-local", "staff")
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("retrade_session", "")
    if not token:
        raise Unauthorized("请先登录")
    return verify_actor(token, c.settings.auth_secret.get_secret_value())


async def require_staff(request: Request) -> Actor:
    """校验当前请求是否来自员工身份。"""
    actor = await authenticate(request)
    request.app.state.container.permission.require_staff(actor)
    return actor
