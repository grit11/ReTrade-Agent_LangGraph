import json
from pathlib import Path
import pytest
from retrade_agent.config import Settings,PROJECT_ROOT
from retrade_agent.storage.sqlite import SqliteRepository
from retrade_agent.services.permission import PermissionService
from retrade_agent.services.orders import OrderService
from retrade_agent.services.human import HumanService
from retrade_agent.services.after_sales import AfterSalesService

@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None,app_env='test',app_mode='offline',data_dir=tmp_path,
                    vector_store='local',redis_url='',rate_limit_per_minute=500)
@pytest.fixture
async def repo(settings):
    r=SqliteRepository(settings.data_dir/'business.sqlite')
    await r.setup(json.loads((PROJECT_ROOT/'resources/fixtures/orders.json').read_text()))
    return r
@pytest.fixture
def permission():return PermissionService()
@pytest.fixture
def orders(repo,permission):return OrderService(repo,permission)
@pytest.fixture
def after_sales(repo,orders):return AfterSalesService(repo,orders)
@pytest.fixture
def human(repo,permission):return HumanService(repo,permission)
