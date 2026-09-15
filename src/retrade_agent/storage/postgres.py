"""PostgreSQL 集成预留模块，本版本有意不启用。

后续应在此处使用 JSONB、数据表和事务实现 domain.ports.StoragePort，并在
application.bootstrap.build_container() 中注册；不要将数据库代码放入图节点。
参考 docs/integration/POSTGRES.md 和 migrations/postgres_contract.sql。
"""
from retrade_agent.errors import ConfigurationError


def create_postgres_repository(settings):
    """创建 PostgreSQL 仓库适配器入口。"""
    raise ConfigurationError("PostgreSQL 业务存储待接入；请先使用 STORAGE_BACKEND=sqlite。参见 docs/integration/POSTGRES.md")
