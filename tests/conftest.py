"""测试夹具模块，为单元、集成和工作流测试提供隔离的服务依赖。"""

import json
from pathlib import Path
import pytest
from retrade_agent.config import Settings, PROJECT_ROOT
from retrade_agent.storage.sqlite import SqliteRepository
from retrade_agent.services.permission import PermissionService
from retrade_agent.services.orders import OrderService
from retrade_agent.services.human import HumanService
from retrade_agent.services.after_sales import AfterSalesService


@pytest.fixture
def settings(tmp_path):
    """创建使用临时数据目录的离线测试配置。"""
    return Settings(
        _env_file=None,
        app_env="test",
        app_mode="offline",
        data_dir=tmp_path,
        vector_store="local",
        redis_url="",
        rate_limit_per_minute=500,
    )


@pytest.fixture
async def repo(settings):
    """初始化包含固定订单数据的临时 SQLite 仓储。"""
    r = SqliteRepository(settings.data_dir / "business.sqlite")
    await r.setup(json.loads((PROJECT_ROOT / "resources/fixtures/orders.json").read_text()))
    return r


@pytest.fixture
def permission():
    """创建权限校验服务。"""
    return PermissionService()


@pytest.fixture
def orders(repo, permission):
    """创建订单领域服务。"""
    return OrderService(repo, permission)


@pytest.fixture
def after_sales(repo, orders):
    """创建售后领域服务。"""
    return AfterSalesService(repo, orders)


@pytest.fixture
def human(repo, permission):
    """创建人工工单服务。"""
    return HumanService(repo, permission)
