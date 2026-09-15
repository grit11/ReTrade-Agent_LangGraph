#!/usr/bin/env bash
# Unix 开发环境启动脚本：创建虚拟环境、安装依赖、准备配置并运行服务。

set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -e '.[dev]'
[ -f .env ] || cp .env.example .env
exec .venv/bin/python scripts/run.py
