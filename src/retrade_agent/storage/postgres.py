"""PostgreSQL integration seam, intentionally NOT active in this delivery.

Implement domain.ports.StoragePort using JSONB/tables and transactions here, then
register it in application.bootstrap.build_container(). Do not put DB code into
Graph nodes. See docs/integration/POSTGRES.md and migrations/postgres_contract.sql.
"""
from retrade_agent.errors import ConfigurationError

def create_postgres_repository(settings):
    raise ConfigurationError('PostgreSQL 业务存储待接入；请先使用 STORAGE_BACKEND=sqlite。参见 docs/integration/POSTGRES.md')
