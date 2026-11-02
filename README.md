# ReTrade Agent

**面向二手交易场景的多智能体客服系统，让规则咨询、订单查询、售后办理与人工协作在同一条会话中完成。**

基于 **LangChain + LangGraph + FastAPI** 构建，结合混合检索 RAG、工具调用、售后状态机与可恢复的人工审批，提供从用户提问到业务处理的完整演示链路。自带 Web 客服控制台、知识中心和评估工具，支持离线体验与云模型接入。

![Python](https://img.shields.io/badge/Python-3.11%E2%80%933.13-3776AB?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1.2.18-1C3C3C)
![LangGraph](https://img.shields.io/badge/LangGraph-1.1.10-1C3C3C)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

![ReTrade Agent 客服控制台](docs/preview/desktop-welcome.png)

> 截图使用项目实际前端与离线 API 夹具，展示界面及交互。默认离线模式使用规则模型与测试向量；切换 `live` 后才调用真实云模型。两种模式下的订单与售后提交均为模拟业务，不执行真实支付、退款或物流操作。

## 目录

- [项目定位](#项目定位)
- [核心能力](#核心能力)
- [业务场景](#业务场景)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [模型与环境配置](#模型与环境配置)
- [API 使用](#api-使用)
- [控制台预览](#控制台预览)
- [Docker 部署](#docker-部署)
- [测试与评估](#测试与评估)
- [项目结构与源码导读](#项目结构与源码导读)
- [常见问题](#常见问题)
- [许可证](#许可证)

## 项目定位

ReTrade Agent 将客服业务拆分为综合客服、订单查询、售后处理和人工服务四个业务域，由 LangGraph 统一管理会话状态与业务流转。综合客服与订单客服通过工具获取知识或业务数据，售后流程通过显式节点完成信息收集、规则校验、用户确认与审批。

项目适合用于学习和验证多智能体协作、RAG 问答、工具权限控制以及 Human-in-the-Loop 工作流，也可以作为接入真实交易系统的开发起点。

| 业务模块 | 负责的问题 | 处理方式 |
| --- | --- | --- |
| 综合客服 | 平台介绍、使用帮助、交易与售后规则咨询 | CustomerAgent 调用知识检索工具，基于检索资料回答 |
| 订单查询 | 当前账户订单、订单详情、物流、支付状态 | OrderAgent 调用订单工具，业务服务校验订单归属 |
| 售后处理 | 退款、退货、商品损坏、描述争议 | AfterSalesGraph 按步骤收集信息、校验政策并处理申请 |
| 人工服务 | 用户主动转人工、需要人工处理的业务、高风险售后审核 | 创建工单、保存图检查点，等待人工处理后恢复 |

## 核心能力

### 多智能体协作与会话状态

- 首次未确定业务域时进行结构化分诊，后续结合活跃业务域与转交工具继续处理。
- CustomerAgent 与 OrderAgent 使用 LangChain `create_agent`，通过工具执行检索和查询。
- 主图统一组织业务分派、跨域转交、人工等待和结果汇总，并限制转交次数与执行步数。
- 会话消息、请求记录、业务状态与 LangGraph 检查点持久化保存，支持多轮追问和人工恢复。

### 混合检索 RAG 与知识中心

- 支持上传 PDF、DOCX、Markdown、TXT 文档，按标题与文本长度分块。
- BM25 与向量检索并行召回，经 RRF 融合后使用可选的 SiliconFlow Reranker 重排。
- 返回资料来源与检索细节，知识中心支持文档列表、上传、删除、重建索引和检索调试。
- 默认使用本地向量索引，可选连接已有 Milvus；云模型模式无需在本地下载推理权重。
- 向量检索失败时可降级到 BM25，重排失败时保留融合排序，并记录降级信息。

### 售后状态机与人工协作

- 将售后办理拆分为信息收集、订单确认、政策检查、用户确认、风险审批与模拟提交。
- 缺少必要信息时继续追问；低风险申请经确认后提交，高风险申请进入人工审核。
- 人工工单支持认领、留言及处理决定，使用版本校验防止并发处理冲突。
- 通过 LangGraph `interrupt` 暂停、检查点持久化和 `Command(resume=...)` 恢复原流程。
- 提交前再次检查订单归属、规则与确认状态，结合幂等记录避免重复创建模拟申请。

### 可观测性与运行支持

- JSON 与 SSE 共用 `WorkflowService` 执行路径，记录阶段、业务域、工具调用与转交事件。
- 使用 `request_id` 关联请求与执行轨迹，结合请求指纹和会话租约控制重复请求与并发执行。
- 受限的公共知识首轮问答可使用精确请求缓存；订单查询不使用该回复缓存。
- 默认 SQLite 存储，也支持 PostgreSQL 业务数据与 LangGraph 检查点，可选 Redis 缓存与限流。
- 提供 Docker Compose、离线 CI 检查及独立的五层评估工具包。

## 业务场景

以下是典型处理路径；实际回复与分支取决于输入、模拟订单状态及模型输出。

| 场景 | 用户输入示例 | 运行流程 |
| --- | --- | --- |
| 综合客服 | “二手商品支持七天无理由退货吗？” | 分诊至 `customer` → `search_knowledge` → 混合检索 → 结合资料解释规则并返回来源 |
| 订单查询 | “帮我看看我的订单。”随后选择订单询问物流 | 分诊或转交至 `order` → `list_orders` → `get_order` / `get_logistics` → 返回当前账户的模拟订单信息 |
| 售后处理 | “我要申请退货，商品没有使用，原因是买错了。” | 进入 `after_sales` → 补充订单等信息 → 检查政策 → 请求用户确认 → 模拟提交或人工审核 |
| 人工服务 | “这个问题请人工客服处理。” | 创建客服工单 → 暂停主图 → 人工认领与回复 → 恢复图并保存处理结果 |

“退货有什么条件”属于规则咨询；“我要为这笔订单申请退货”属于实际办理。售后申请还需要订单、原因等必要信息，以及明确的用户确认。

人工等待期间，用户可以继续补充信息，这些内容会保存到会话与工单。恢复业务流程需要工作人员完成相应处理决定。

## 系统架构

```mermaid
flowchart TD
    UI[Web 客服控制台] --> API[FastAPI：身份校验 / JSON / SSE]
    API --> WF[WorkflowService：会话 / 幂等 / 事件 / 追踪]
    WF --> CTX[加载会话上下文]
    CTX --> ROUTE{已有业务域或首次分诊}
    ROUTE --> CUSTOMER[CustomerAgent 综合客服]
    ROUTE --> ORDER[OrderAgent 订单客服]
    ROUTE --> AFTER[AfterSalesGraph 售后子图]
    ROUTE --> HUMAN[人工工单与图中断]
    CUSTOMER --> KB[KnowledgeService 混合检索]
    ORDER --> OS[OrderService 订单权限与模拟数据]
    AFTER --> POLICY[信息收集 / 政策 / 确认 / 模拟提交]
    POLICY -->|需要审核| HUMAN
    HUMAN -->|人工处理后恢复| WF
    CUSTOMER --> RESULT[结果评估 / 业务转交 / 回复汇总]
    ORDER --> RESULT
    POLICY --> RESULT
    RESULT --> WF
    WF <--> DB[(SQLite / PostgreSQL 业务数据与图检查点)]
    KB --> RETRIEVE[BM25 + 向量召回 → RRF → 可选重排]
```

主图负责“由谁处理、是否转交、何时暂停”；Agent 负责调用工具；业务服务负责权限与规则；存储层负责数据与检查点。售后子图把有前置条件的业务操作组织为明确的状态转换。

## 技术栈

| 层次 | 技术与用途 |
| --- | --- |
| 后端 | Python 3.11–3.13、FastAPI、Uvicorn、Pydantic 2 |
| 智能体 | LangChain 1.2.18、LangGraph 1.1.10、`langchain-openai` |
| 模型接入 | OpenAI 兼容接口，分别配置生成模型、Embedding 与 Reranker |
| 知识检索 | jieba、BM25、向量检索、RRF、远程重排 |
| 文档解析 | pypdf、python-docx、Markdown / 纯文本加载器 |
| 存储 | SQLite 或 PostgreSQL；可选 Milvus、Redis |
| 前端 | 原生 HTML / CSS / JavaScript、Fetch、SSE，无需前端构建步骤 |
| 工程与评估 | pytest、GitHub Actions、Docker Compose、可选独立 Judge / RAGAS 评分 |

## 快速开始

### 1. 获取代码与安装依赖

建议使用 Python 3.11 或 3.12。以下命令在 Windows PowerShell 中执行：

```powershell
git clone https://github.com/grit11/ReTrade-Agent_LangGraph.git
cd ReTrade-Agent_LangGraph

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# 首次配置时复制；已有 .env 时直接编辑，保留现有配置。
Copy-Item .env.example .env
python scripts/run.py
```

macOS / Linux 对应使用 `source .venv/bin/activate` 激活环境，使用 `cp .env.example .env` 初始化配置，其余 Python 命令相同。

### 2. 打开控制台

| 地址 | 用途 |
| --- | --- |
| [http://127.0.0.1:8000](http://127.0.0.1:8000) | 客服对话、订单、人工工单和知识中心 |
| [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | Swagger API 文档 |
| [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) | 运行模式、知识库状态与启动告警 |

默认 `APP_MODE=offline`，无需 API Key 即可体验规则模型驱动的流程。开发环境提供 `demo-customer` 与 `demo-other` 两个客户身份；人工工单和知识管理使用管理员身份，模板中的本地演示密钥为 `dev-admin-change-me`。

### 3. 体验一条完整业务链路

1. 登录演示客户，询问平台或退货规则，查看知识来源。
2. 查询当前账户订单，再选择订单询问详情、物流或支付状态。
3. 对该订单发起售后，补齐信息并确认申请，观察业务状态变化。
4. 发送“转人工”，在人工工作台认领工单、回复并完成处理，返回会话查看结果。

开发时可使用 `python scripts/run.py --reload`；修改监听端口可使用 `--port 8001`。

## 模型与环境配置

### 接入真实云模型

编辑项目根目录 `.env`，切换为 `live` 并配置服务地址、模型名称和密钥。下面沿用模板中的服务示例，模型名称与可用权限以提供商为准：

```dotenv
APP_ENV=dev
APP_MODE=live

AIROBOT_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AIROBOT_LLM_MODEL=qwen-plus
AIROBOT_LLM_API_KEY=your-llm-api-key
AIROBOT_STRUCTURED_OUTPUT_METHOD=function_calling
AIROBOT_LLM_EXTRA_BODY={}

AIROBOT_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
AIROBOT_EMBEDDING_MODEL=Pro/BAAI/bge-m3
AIROBOT_EMBEDDING_API_KEY=your-embedding-api-key

AIROBOT_RERANK_ENABLED=true
AIROBOT_RERANK_BASE_URL=https://api.siliconflow.cn/v1
AIROBOT_RERANK_MODEL=BAAI/bge-reranker-v2-m3
AIROBOT_RERANK_API_KEY=your-rerank-api-key
```

修改后重启服务。生成模型需要同时适配 Agent 工具调用和分诊、售后抽取所需的结构化输出。`live` 模式要求提供 LLM 与 Embedding 密钥；暂不接入重排时可设置 `AIROBOT_RERANK_ENABLED=false`。

### 常用环境变量

完整模板见 [.env.example](.env.example)，校验逻辑见 [config.py](src/retrade_agent/config.py)。

| 配置项 | 默认值 / 说明 |
| --- | --- |
| `APP_ENV` / `APP_MODE` | `dev` / `offline`；真实模型使用 `live` |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` |
| `DATA_DIR` | `./runtime`，保存本地业务数据、知识资料与检查点 |
| `AUTH_SECRET` / `ADMIN_API_KEY` | 身份签名密钥 / 管理员 API 密钥；模板值用于本地开发 |
| `AIROBOT_LLM_TIMEOUT` | 单次模型调用超时，默认 45 秒 |
| `AIROBOT_STRUCTURED_OUTPUT_METHOD` | 默认 `function_calling`；可选 `json_schema`、`json_mode`，需匹配模型能力 |
| `AIROBOT_LLM_EXTRA_BODY` | 默认 `{}`，传入提供商支持的额外 JSON 参数 |
| `AIROBOT_VECTOR_STORE` | 默认 `local`；可选连接已有 `milvus` 服务 |
| `AIROBOT_TOP_K` | 最终检索片段数，默认 5 |
| `AIROBOT_CHUNK_SIZE` / `AIROBOT_CHUNK_OVERLAP` | 分块长度 500 / 重叠 80 |
| `AIROBOT_HYBRID_VECTOR_TOP_K` / `AIROBOT_HYBRID_BM25_TOP_K` | 两路召回各 15 条，融合候选数由 `AIROBOT_HYBRID_FUSION_TOP_K=10` 控制 |
| `AIROBOT_CACHE_ENABLED` / `CACHE_TTL_SECONDS` | 默认开启受限回复缓存，TTL 为 300 秒 |
| `REDIS_URL` | 留空时使用本地 TTL 缓存与本地限流 |
| `AIROBOT_RATELIMIT_PER_MINUTE` | 每客户每分钟请求限制，默认 60 |
| `MAX_HANDOFFS` / `MAX_AGENT_STEPS` | 默认最多转交 3 次、Agent 执行 12 步 |
| `MAX_REQUEST_SECONDS` / `MAX_UPLOAD_MB` | 请求总时限 180 秒 / 上传文件上限 10 MB |
| `STORAGE_BACKEND` / `CHECKPOINT_BACKEND` | 默认均为 `sqlite`；设置为 `postgres` 后使用 PostgreSQL 业务表和图检查点 |

连接 Milvus 前安装 `python -m pip install -e ".[milvus]"`，并配置 `AIROBOT_MILVUS_URI` 等参数。使用 PostgreSQL 前安装 `python -m pip install -e ".[postgres]"`，创建目标数据库，然后设置 `STORAGE_BACKEND=postgres`、`CHECKPOINT_BACKEND=postgres` 和同一个 `ASYNC_DATABASE_URL`。应用启动时会自动创建业务表、索引和模拟订单。

```powershell
$env:POSTGRES_ADMIN_DSN = "postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/postgres"
python scripts/create_postgres_db.py --database retrade_agent
Remove-Item Env:POSTGRES_ADMIN_DSN
```

数据库创建后，在 `.env` 中配置：

```dotenv
STORAGE_BACKEND=postgres
CHECKPOINT_BACKEND=postgres
ASYNC_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/retrade_agent
LANGGRAPH_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/retrade_agent
```

Windows 请通过 `python scripts/run.py` 启动，脚本会为 PostgreSQL 设置兼容的 Selector 事件循环。连接密码含 `@`、`:` 等 URI 特殊字符时需要 URL 编码。Docker 连接宿主机 PostgreSQL 时，把连接串中的 `127.0.0.1` 替换为 `host.docker.internal`，并通过 `RETRADE_EXTRAS=postgres` 安装镜像中的可选依赖。

## API 使用

### 常用接口

| 方法 | 路径 | 说明 / 权限 |
| --- | --- | --- |
| `GET` | `/health` | 应用与知识库状态，公开访问 |
| `POST` | `/api/v1/auth/demo` | 开发 / 测试环境签发演示登录 Cookie |
| `GET` | `/api/v1/auth/me` | 当前身份 |
| `POST` / `GET` | `/api/v1/sessions` | 创建 / 列出当前客户会话 |
| `GET` | `/api/v1/sessions/{session_id}` | 会话详情与历史消息 |
| `POST` | `/api/v1/chat` | JSON 聊天响应 |
| `POST` | `/api/v1/chat/stream` | SSE 阶段事件与最终响应 |
| `GET` | `/api/v1/orders` | 当前客户可见的模拟订单 |
| `GET` | `/api/v1/traces/{request_id}` | 当前客户请求的执行轨迹 |
| `GET` | `/api/v1/human/tickets` | 人工工单列表，员工权限 |
| `POST` | `/api/v1/human/tickets/{ticket_id}/claim` | 认领工单，需版本号 |
| `POST` | `/api/v1/human/tickets/{ticket_id}/messages` | 员工工单留言 |
| `POST` | `/api/v1/human/resume` | 提交 `resolve` / `approve` / `reject` 决定并恢复流程 |
| `GET` | `/api/v1/knowledge` | 文档列表与索引状态，员工权限 |
| `POST` | `/api/v1/knowledge/ingest` | 上传文档，`multipart/form-data` |
| `POST` | `/api/v1/knowledge/rebuild` | 重建知识索引 |
| `POST` | `/api/v1/knowledge/search` | 检索调试 |
| `DELETE` | `/api/v1/knowledge/{document_id}` | 删除文档并刷新索引 |

客户接口通过签名 Cookie 或 Bearer 令牌识别访问者；管理员接口支持 `X-Admin-Token`。订单归属以服务端身份为准。完整字段和约束以运行中的 `/docs` 为准。

### 从登录到发送消息

PowerShell 示例使用 Cookie 保持同一客户身份，先创建会话，再发送中文消息：

```powershell
$baseUrl = "http://127.0.0.1:8000"

Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/auth/demo" `
    -ContentType "application/json" -Body '{"user":"demo-customer"}' `
    -SessionVariable retradeSession

$session = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/sessions" `
    -ContentType "application/json" -Body '{}' -WebSession $retradeSession

$payload = @{
    session_id = $session.session_id
    request_id = [guid]::NewGuid().ToString()
    message = "平台支持哪些退货方式？"
} | ConvertTo-Json

$result = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/chat" `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($payload)) `
    -WebSession $retradeSession

$result | ConvertTo-Json -Depth 10
```

`session_id` 和 `request_id` 均为 UUID。新消息使用新的 `request_id`，重试同一请求时复用原编号与内容。响应包含 `reply`、`domain`、`status`、`sources`、`used_tools`、`waiting_human`、`ticket_id`、`total_ms` 等字段。

### SSE 事件

流式接口与 JSON 接口使用相同请求结构，通过 `data: {...}` 推送事件，JSON 中的 `type` 区分 `stage`、`domain`、`tool`、`handoff`、`human_wait`、`token`、`done`、`error`。

阶段和工具事件随执行过程推送；最终正文在汇总后通过带有 `buffered: true` 的 `token` 事件发送。当前实现属于过程事件流，正文采用整段发送方式。

## 控制台预览

控制台集成客服会话、订单查看、人工工单和知识管理，前后端由同一 FastAPI 服务提供。

![客服对话与执行信息](docs/preview/desktop-conversation.png)

<details>
<summary>查看人工工作台、知识中心与移动端界面</summary>

**人工工作台**

![人工工单工作台](docs/preview/desktop-human.png)

**知识中心**

![知识文档管理](docs/preview/desktop-knowledge.png)

**移动端**

<img src="docs/preview/mobile-welcome.png" alt="移动端客服界面" width="360">

</details>

截图生成说明见 [docs/preview/README.md](docs/preview/README.md)。

## Docker 部署

先按上述步骤准备 `.env`，然后在项目根目录执行：

```bash
docker compose up -d --build
docker compose logs -f retrade
```

Compose 启动应用与 Redis，默认通过 [http://127.0.0.1:8000](http://127.0.0.1:8000) 访问。业务运行目录与 Redis 数据分别写入命名卷，模型服务和 Milvus 需要自行配置。

默认部署采用单个 Uvicorn worker 和 SQLite。正式环境需要接入真实身份服务、配置 HTTPS 与业务后端，并更换开发密钥；`APP_ENV=prod` 会禁用演示登录，要求 `live` 模式、至少 32 字符的随机 `AUTH_SECRET` 和至少 24 字符的管理员密钥。安全设计见 [docs/SECURITY.md](docs/SECURITY.md)。

## 测试与评估

### 工程检查

```bash
python -m pip check
python -m compileall -q src scripts tests
python -m pytest tests -q
node --check frontend/app.js
node --check frontend/api.js
node tests/e2e/test_sse_parser.mjs
```

[GitHub Actions](.github/workflows/ci.yml) 在 Python 3.11 下执行依赖检查、Python 编译、离线单元 / 集成 / 图运行测试和前端 JavaScript 语法检查。SSE 解析测试与下面的评估工具可单独运行。

PostgreSQL 集成测试默认跳过。安装 `.[postgres]` 后，可在 PowerShell 中连接测试数据库运行；测试创建随机 schema 并在结束时清理，不修改现有业务表，也不调用云模型：

```powershell
$env:RETRADE_TEST_POSTGRES_DSN = "postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/retrade_agent"
python -m pytest tests/integration/test_postgres.py -q
Remove-Item Env:RETRADE_TEST_POSTGRES_DSN
```

### 五层评估

评估工具直接调用项目的知识服务和工作流，记录实际工具轨迹，并将答案生成与质量评分分开执行。

| 评估层 | 初始数据 | 关注内容 |
| --- | --- | --- |
| 检索质量 | 72 条知识题 | 证据 Hit@K、Recall@K、MRR、耗时、降级；比较混合检索 / BM25 / 向量检索 |
| 回答质量 | 72 条知识题 + 12 条订单题 | 业务路由、工具参数、事实规则检查；可选独立 Judge 与 RAGAS |
| 业务流程 | 32 个多轮场景、62 个动作 | 状态转换、信息补充、确认、审批、取消、幂等回执 |
| 系统可靠性 | 16 个故障 / 隔离场景及可配置并发请求 | 鉴权、重复请求、冲突、超时、恢复、延迟与错误 |
| 业务效果 | 12 条合成演示记录及生产数据模板 | 已核实解决率、复联、转人工、CSAT 与成本统计 |

```bash
python evaluation/run.py validate
python evaluation/run.py retrieval --strategies hybrid bm25 vector --out evaluation/reports/latest/retrieval
python evaluation/run.py answers --out evaluation/reports/latest/knowledge
python evaluation/run.py answers --dataset evaluation/data/orders.jsonl --out evaluation/reports/latest/orders
python evaluation/run.py workflow --out evaluation/reports/latest/workflow
python evaluation/run.py reliability --out evaluation/reports/latest/reliability
python evaluation/run.py load --requests 20 --concurrency 4 --out evaluation/reports/latest/load
python -m pytest evaluation/tests -q
```

每套评估输出 JSON、JSONL 与 Markdown 报告，`--out` 指定输出目录。真实模型评估需显式传入 `--mode live --allow-live`；Judge / RAGAS 使用独立评分配置与可选依赖，详见 [评估工具说明](evaluation/README.md)。

仓库中的离线报告用于实现回归，规则命中率不等同于回答准确率，合成业务数据也不代表实际业务收益。评估数据、历史报告及其适用范围均在评估目录中说明，当前代码的结果应通过重新执行获得。

## 项目结构与源码导读

```text
ReTrade-Agent_LangGraph/
├── src/retrade_agent/
│   ├── api/                 # HTTP 接口、身份校验、聊天流、人工与知识管理
│   ├── agents/              # 综合客服 / 订单 Agent、工具、执行适配与离线模型
│   ├── graph/               # 主客服图、售后子图、图状态与事件
│   ├── services/            # 知识、订单、售后、人工和权限服务
│   ├── rag/                 # 加载、分块、BM25、向量、融合与重排
│   ├── storage/             # 业务仓储、检查点、缓存与外部连接
│   ├── bootstrap.py         # 依赖装配与资源生命周期
│   ├── workflow.py          # 会话执行入口、幂等、事件与持久化
│   ├── config.py            # 环境配置与启动校验
│   ├── llm.py               # 模型工厂与结构化输出
│   ├── models.py            # 公共数据模型
│   ├── text.py              # 文本识别辅助函数
│   └── errors.py            # 应用异常
├── frontend/                # 原生 Web 控制台
├── resources/knowledge/     # 初始知识库
├── scripts/                 # 启动、诊断、知识导入等脚本
├── tests/                   # 单元、集成、图运行与前端测试
├── evaluation/              # 五层评估工具、数据与报告
├── eval/                    # 基础检索回归脚本与数据
├── docs/                    # 架构、安全、设计决策与预览资料
├── .github/workflows/       # 离线 CI
├── .env.example             # 环境变量模板
├── docker-compose.yml       # 应用与 Redis 编排
└── pyproject.toml           # Python 依赖与开发配置
```

第一次阅读代码，建议先沿请求入口理解主链路，再分别展开各业务域：

| 阅读目标 | 推荐入口与调用关系 |
| --- | --- |
| 服务如何启动 | [scripts/run.py](scripts/run.py) → [api/app.py](src/retrade_agent/api/app.py) 的 `create_app()` → [bootstrap.py](src/retrade_agent/bootstrap.py) 的 `build_container()` |
| 一条消息如何执行 | [api/chat.py](src/retrade_agent/api/chat.py) → [workflow.py](src/retrade_agent/workflow.py) 的 `WorkflowService` → [graph/support.py](src/retrade_agent/graph/support.py) 的 `build_parent()` |
| 综合客服如何查资料 | [agents/customer.py](src/retrade_agent/agents/customer.py) → [agents/knowledge_tools.py](src/retrade_agent/agents/knowledge_tools.py) → [services/knowledge.py](src/retrade_agent/services/knowledge.py) → [rag/retriever.py](src/retrade_agent/rag/retriever.py) |
| 订单查询如何校验权限 | [agents/order.py](src/retrade_agent/agents/order.py) → [agents/order_tools.py](src/retrade_agent/agents/order_tools.py) → [services/orders.py](src/retrade_agent/services/orders.py) |
| 售后为何追问、确认或审批 | [graph/after_sales.py](src/retrade_agent/graph/after_sales.py) → [services/after_sales.py](src/retrade_agent/services/after_sales.py) |
| 人工处理后如何恢复 | [api/human.py](src/retrade_agent/api/human.py) → [services/human.py](src/retrade_agent/services/human.py) → `WorkflowService` 恢复被中断的图 |
| 数据与图进度存在哪里 | [storage/sqlite.py](src/retrade_agent/storage/sqlite.py) 或 [storage/postgres.py](src/retrade_agent/storage/postgres.py) 保存业务记录；[storage/checkpoint.py](src/retrade_agent/storage/checkpoint.py) 管理官方图检查点保存器 |

## 常见问题

**离线模式为什么回答较固定？**

`offline` 使用脚本化规则模型和测试向量，便于验证接口与流程。需要自然语言生成和真实语义检索时，配置密钥并切换为 `live`。

**模型对话成功，为什么首次分诊或售后解析仍然失败？**

普通对话、Agent 工具调用和结构化输出使用不同的请求能力。先核对服务是否支持当前 `AIROBOT_STRUCTURED_OUTPUT_METHOD`，再检查工具调用、超时与提供商额外参数。部分思考模型限制强制工具选择；仅在服务明确支持时，可通过 `AIROBOT_LLM_EXTRA_BODY={"thinking":{"type":"disabled"}}` 关闭思考模式。当前分诊或售后抽取失败的部分路径会进入人工工单，可结合请求轨迹与服务日志定位。

**`/health` 显示正常，是否代表所有模型服务都能调用？**

该接口返回应用配置、知识库就绪状态和启动告警，不会完整探测生成模型、Embedding、重排与结构化输出。应进一步通过聊天、知识检索及具体业务流程验证。

**为什么订单查不到？**

先使用当前账户订单列表核对订单号与身份。订单服务接受 6–20 位数字订单号，并只返回当前客户可访问的数据；不存在与不属于当前账户的订单使用相同的公开提示。自然语言识别问题还需结合 `used_tools` 与工具参数检查。

**人工已经留言，为什么流程还在等待？**

留言与完成处理是两个动作。普通客服工单需提交 `resolve`，审批工单需提交 `approve` 或 `reject`；恢复请求还需要匹配工单及其当前版本。

**可以直接切换到 PostgreSQL 保存全部业务数据吗？**

PostgreSQL 模式现在同时保存业务实体、会话消息、运行回执、工单、售后记录、知识登记、追踪和会话租约，并由 LangGraph 保存检查点。业务表会在应用启动时自动创建；`scripts/create_postgres_db.py` 只负责创建数据库本身。切换前请先备份 SQLite 数据，当前实现不会自动把已有 `runtime/business.sqlite` 迁移到 PostgreSQL。

## 许可证

本项目采用 [MIT License](LICENSE)。
