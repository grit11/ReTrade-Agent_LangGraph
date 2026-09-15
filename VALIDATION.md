# 交付验证记录 · v0.1.0

日期：2026-09-14。**这是代码交付与已执行测试的记录，不是生产上线验收报告。**

## 1. 实际已执行

| 检查 | 结果 | 实际覆盖范围 |
|---|---|---|
| Python compileall | 通过 | src、scripts、tests、eval 的语法编译 |
| pytest 单元与 HTTP 合同测试 | **51 passed** | 配置、权限、SQLite 持久化/幂等/租约、模拟售后、工单、RAG、FastAPI JSON/SSE 协议 |
| 真实 Graph 测试模块 | **1 module skipped** | 该模块包含6个实际 LangGraph/create_agent 场景；本环境未执行 |
| JavaScript 语法 | 通过 | frontend/app.js、frontend/api.js |
| JavaScript SSE/API 解析测试 | **4 assertions passed** | UTF-8 分片、SSE帧、错误处理、请求构造 |
| 离线浏览器界面检查 | **7 passed / 0 page errors** | 当前前端源文件 + 内存API夹具；桌面/390px手机、会话、来源、工单、知识中心、配置 |
| 原知识文档与QA数据迁移 | 两个 Git blob SHA 均匹配 | 原文档1551字节，QA11886字节/52条 |
| 离线检索回归 | 52条读取完成 | 47条非缺失知识样本的关键词代理命中47条；**不代表回答正确率或真实向量质量** |

HTTP 合同测试使用真实 FastAPI、鉴权和 SQLite 仓储，但注入了显式 Workflow 测试替身；没有冒充真实图运行。
浏览器检查使用实际 HTML/CSS/JS 与内存API夹具。浏览器环境禁止访问本机服务器，因此未做浏览器到实际后端的联合测试。
离线检索采用确定性散列向量与测试环境分词后备实现，不是线上 Embedding 模型。

## 2. 未执行的关键联调

本执行环境无法通过 DNS 访问 PyPI；没有安装 langchain/langgraph 等运行时包。安装尝试失败，因此以下能力虽已编写代码和测试入口，**未在本交付环境完成验证**：

- 真正的 create_agent 执行、Agent子图嵌套、ToolRuntime注入与ToolMessage artifact回传。
- LangGraph SQLite Checkpointer、interrupt/resume、人工审批与服务重启恢复。
- DashScope/DeepSeek等真实模型、SiliconFlow Embedding/Rerank请求。
- 实际 Milvus、Redis 和可选PostgreSQL Checkpointer连接。
- 完整依赖求解、pip check、Docker镜像构建和目标Python3.11安装。

没有调用用户真实密钥，没有连接用户远程数据库，没有进行真实资金操作。
订单和售后服务始终是明确标注的模拟实现；PostgreSQL业务存储端口按本轮需求保留待接入。

## 3. 目标机器验收命令

在独立目录、Python3.11虚拟环境中运行：

```powershell
python -m pip install -e ".[dev]"
python -m pip check
python scripts/doctor.py
python scripts/check_project.py
python -m pytest tests/unit tests/integration tests/graph -q -rs
python scripts/run.py
```

安装完成后的 Graph 测试**不应跳过**；如果仍跳过，请处理环境和依赖再进行验收。
另开终端，在服务运行期间：

```powershell
python scripts/smoke_test.py
node tests/e2e/test_sse_parser.mjs
# 可选：安装 .[ui-test] 并按 Playwright 指引安装 Chromium 后
python tests/e2e/browser_smoke.py
```

真实API模式：先用 scripts/import_env.py 导入自己的私有 .env，再将 APP_MODE=live；逐项确认知识、订单、跨域、售后、人工恢复。
运行 smoke_test.py 的真实API版本必须显式添加 --allow-live，避免意外产生模型调用费用。

## 4. 输出语义与安全边界

SSE实时输出流程阶段、工具和业务域事件。最终答案通过证据/业务检查后以缓冲的 `token` 事件发布，标记 `buffered=true`，**不是逐模型token流**。
来源取自实际工具artifact，不由模型自行填写；这只能检查证据链存在，不是对每句话忠实性的形式化证明。
默认单worker、本地开发身份。公开部署前需正式身份服务、依赖安全升级、外部接口联调、隐私与负载测试。

## 5. 记录文件

- docs/validation/pytest.txt / junit.xml：已运行51项测试与跳过记录。
- docs/validation/browser_ui.json：离线界面检查结果及范围。
- docs/validation/retrieval_offline.json：离线关键词代理评测。
- RELEASE_MANIFEST.json：源码基线、文件校验和与验证摘要。

真实运行是否通过，应以目标机器测试结果为准，而不是仅凭“源码已生成”判断。
