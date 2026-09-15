"""Official checkpoint adapters, selected explicitly; no silent fallback."""
import os
from contextlib import asynccontextmanager
from retrade_agent.errors import ConfigurationError

@asynccontextmanager
async def open_checkpointer(settings):
    os.environ.setdefault('LANGGRAPH_STRICT_MSGPACK','true')
    if settings.checkpoint_backend == 'postgres':
        dsn=settings.langgraph_database_url.get_secret_value() or settings.async_database_url.get_secret_value()
        dsn=dsn.replace('postgresql+asyncpg://','postgresql://',1)
        if not dsn:
            raise ConfigurationError('PostgreSQL Checkpointer 未配置 DSN')
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:
            raise ConfigurationError('请先安装 pip install -e ".[postgres]"') from exc
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            await saver.setup()
            yield saver
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        settings.data_dir.mkdir(parents=True,exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir/'checkpoints.sqlite')) as saver:
            await saver.setup()
            yield saver
