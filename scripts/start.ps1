# Windows 开发环境启动脚本：创建虚拟环境、安装依赖、准备配置并运行服务。

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (!(Test-Path '.venv')) { py -3.11 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败；请检查 Python 3.11 和网络。' }
if (!(Test-Path '.env')) { Copy-Item .env.example .env }
& .\.venv\Scripts\python.exe scripts\run.py
