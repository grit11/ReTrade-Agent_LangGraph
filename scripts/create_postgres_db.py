"""创建 ReTrade Agent 使用的 PostgreSQL 数据库。

该脚本连接 PostgreSQL 管理库执行 CREATE DATABASE；业务表会在应用启动时
由 PostgresRepository.setup() 自动创建。密码通过 DSN 或环境变量提供，
不会写入项目文件。
"""

import argparse
import os
import sys


def main() -> int:
    """解析参数并创建目标数据库。"""
    parser = argparse.ArgumentParser(description="Create a PostgreSQL database for ReTrade Agent")
    parser.add_argument(
        "--dsn",
        default=os.getenv("POSTGRES_ADMIN_DSN") or os.getenv("ASYNC_DATABASE_URL"),
        help="管理连接 DSN；默认读取 POSTGRES_ADMIN_DSN 或 ASYNC_DATABASE_URL",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="目标数据库名；默认读取 DSN 中的 dbname，或 retrade_agent",
    )
    parser.add_argument(
        "--admin-database",
        default="postgres",
        help="用于执行 CREATE DATABASE 的管理库，默认 postgres",
    )
    args = parser.parse_args()
    if not args.dsn:
        parser.error("请通过 --dsn 或 POSTGRES_ADMIN_DSN / ASYNC_DATABASE_URL 提供 PostgreSQL DSN")

    try:
        from psycopg import connect
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        from psycopg.sql import Identifier, SQL
    except ImportError:
        print('请先安装 PostgreSQL 依赖：python -m pip install -e ".[postgres]"', file=sys.stderr)
        return 2

    info = conninfo_to_dict(args.dsn)
    target = args.database or info.get("dbname") or "retrade_agent"
    admin_info = dict(info)
    admin_info["dbname"] = args.admin_database
    admin_dsn = make_conninfo(**admin_info)

    try:
        with connect(admin_dsn, autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
            if exists:
                print(f"数据库已存在：{target}")
                return 0
            conn.execute(SQL("CREATE DATABASE {}").format(Identifier(target)))
    except Exception as exc:
        print(f"创建数据库失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"数据库创建成功：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
