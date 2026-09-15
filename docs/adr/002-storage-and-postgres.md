# ADR 002：本轮采用 SQLite，PostgreSQL 保留接入边界

用户最新要求优先于旧 MVP 的 PostgreSQL 必选项。现在无需任何远程数据库即可启动。

- business.sqlite：会话、公开消息、请求回执、工单、售后、知识登记、追踪、会话租约。
- checkpoints.sqlite：官方 AsyncSqliteSaver 管理，不能当普通业务表修改。
- storage_backend=postgres：明确报 ConfigurationError，不静默假装已接 PostgreSQL。
- domain/ports.py: StoragePort 是后续业务数据库实现接口。
- infrastructure/db/repositories/postgres.py: 接入入口，替换实现即可，不改 Agent/Graph。
- checkpoint_backend=postgres：已提供可选 AsyncPostgresSaver 适配器，需装 .[postgres]；本次未远程联调。

PostgreSQL 业务表迁移时实现 entities(JSONB)、messages、runs、operations、traces、leases 的等价约束。
尤其保留 operations.id 唯一键和指纹、runs.id 幂等校验、ticket version 乐观锁、session 并发互斥。
SQLite 的两个文件不是同一事务；通过稳定 ID、请求回执和 resume reconciliation 补偿崩溃窗口。
这不是对任意外部支付系统的 exactly-once 保证。未来真实写接口也必须支持自己的幂等键。

示例（只填自己的私有 .env，不提交）：
```env
STORAGE_BACKEND=sqlite
CHECKPOINT_BACKEND=postgres
ASYNC_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB
LANGGRAPH_DATABASE_URL=
```
业务 PostgreSQL 尚未接入时，STORAGE_BACKEND 仍保持 sqlite。
