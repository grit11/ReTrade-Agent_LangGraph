# ADR 002：SQLite 与 PostgreSQL 双存储适配

默认使用 SQLite，保证离线开发无需数据库服务；配置 `STORAGE_BACKEND=postgres` 后，业务数据切换到 PostgreSQL，配置 `CHECKPOINT_BACKEND=postgres` 后 LangGraph 检查点也切换到 PostgreSQL。

- business.sqlite：会话、公开消息、请求回执、工单、售后、知识登记、追踪、会话租约。
- checkpoints.sqlite：官方 AsyncSqliteSaver 管理，不能当普通业务表修改。
- storage_backend=postgres：使用 `storage.postgres.PostgresRepository`，通过 JSONB 保存业务实体。
- storage/contracts.py: StoragePort 约束 SQLite 与 PostgreSQL 的共同接口。
- storage/postgres.py: PostgreSQL 业务仓储，替换实现不改 Agent/Graph。
- checkpoint_backend=postgres：使用官方 `AsyncPostgresSaver`，需安装 `.[postgres]`。

PostgreSQL 使用 `retrade_` 前缀的 entities(JSONB)、messages、runs、operations、traces、leases 业务表。
尤其保留 operations.id 唯一键和指纹、runs.id 幂等校验、ticket version 乐观锁、session 并发互斥。
SQLite 的两个文件不是同一事务；通过稳定 ID、请求回执和 resume reconciliation 补偿崩溃窗口。
这不是对任意外部支付系统的 exactly-once 保证。未来真实写接口也必须支持自己的幂等键。

示例（只填自己的私有 .env，不提交）：
```env
STORAGE_BACKEND=postgres
CHECKPOINT_BACKEND=postgres
ASYNC_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB
LANGGRAPH_DATABASE_URL=
```
应用启动时会自动创建 PostgreSQL 业务表和索引；`scripts/create_postgres_db.py` 只创建目标数据库。当前没有自动迁移既有 SQLite 数据的功能，切换前需要自行导出或重新导入业务数据。
