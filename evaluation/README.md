# ReTrade Agent · 五层评估工具包

本目录把现有的“检索关键词命中检查”扩展为：**检索质量、回答质量、业务流程、系统可靠性、业务效果**五层评估。它调用当前项目的真实 `KnowledgeService`、`WorkflowService` 和 LangGraph，并记录实际工具轨迹；答案评分与答案生成分开运行。

适配基线：[ReTrade-Agent_LangGraph / b9231b4](https://github.com/grit11/ReTrade-Agent_LangGraph/tree/b9231b494986d76836d45495c243f8205a526fb1)。测试日期：2026-09-16。若你的本地代码已有修改，请重新执行评估；报告会记录实际 `src/` 指纹。

工具包只新增 `evaluation/`。解压后把此目录放到项目根目录，与 `src/`、`resources/`、`pyproject.toml` 同级。它不覆盖原来的 `eval/runners/retrieval.py`，也不修改业务实现。

**先明确结果边界：**默认 `offline` 使用项目自带的规则模型和测试向量；`live` 才使用你配置的真实生成模型、Embedding 和可选 Reranker。两种模式的订单、退款仍然都是项目模拟服务。随包没有真实用户生产数据，也没有付费模型评分成绩。

## 1. 先跑起来

所有命令均在**项目根目录**执行，可直接用于已激活环境的 PowerShell、终端或 VS Code。

```bash
python -m pip install -e ".[dev]"
python evaluation/run.py validate

# 检索：同时比较混合检索、BM25、向量检索
python evaluation/run.py retrieval --strategies hybrid bm25 vector --out evaluation/reports/latest/retrieval

# 回答：实际运行完整客服图，分别评估知识题和订单题
python evaluation/run.py answers --out evaluation/reports/latest/knowledge
python evaluation/run.py answers --dataset evaluation/data/orders.jsonl --out evaluation/reports/latest/orders

# 多轮流程与故障注入
python evaluation/run.py workflow --out evaluation/reports/latest/workflow
python evaluation/run.py reliability --out evaluation/reports/latest/reliability

# 本地 Workflow 并发基线
python evaluation/run.py load --requests 20 --concurrency 4 --out evaluation/reports/latest/load

# 仅演示业务统计计算；不是生产效果
python evaluation/run.py business --demo --as-of 2026-09-16T00:00:00Z --out evaluation/reports/latest/business_demo
```

每次运行输出三种文件：`<suite>.json` 是完整报告，`<suite>.jsonl` 是逐样本记录，`<suite>.md` 是可读汇总。`--out` 表示**目录**。知识题和订单题都是 `answers`，请使用不同输出目录，避免相互覆盖。

第一次调试可以添加 `--limit 5`。`retrieval/answers/workflow/reliability` 支持 `--split dev`、`--split test`、`--repeats N`。可靠性集全部为 `dev`，因此它没有 `test` 子集。`load` 使用 `--requests` 和 `--concurrency`。

```bash
python -m pytest evaluation/tests -q
python -m pytest tests -q
```

没有安装 RAGAS 时，RAGAS 适配器测试会跳过，其余基础评估可以运行。`--fail-on-regression` 让执行错误或规则失败返回退出码 2，便于 CI；它不代表自动评估全部语义质量。检索没有设定统一通过阈值，低召回率本身不会触发该退出码。配置错误返回 1，正常生成报告返回 0。

## 2. 五层分别回答什么问题


| 评估层     | 实际入口                                | 数据                            | 已实现的指标/检查                                                                | 不能据此推断的结论                           |
| ------------ | ----------------------------------------- | --------------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------- |
| 检索质量   | `KnowledgeService`、`HybridRetriever`   | 72 条知识题                     | 证据 Hit@K、证据单元 Recall@K、MRR@K、已标注片段精度代理、关键词基线、耗时、降级 | 不能证明最终回答正确                         |
| 回答质量   | 完整图中的`CustomerAgent`、`OrderAgent` | 72 条知识题 + 12 条订单题       | 路由/工具参数、事实文本代理、禁止内容、RAGAS 四指标、独立 Judge、人工评审导出    | 规则通过不等于语义正确；Judge 分数需人工校准 |
| 业务流程   | `SupportGraph`、`AfterSalesGraph`       | 32 个场景、62 个动作            | 多轮任务成功率、状态转换、工具轨迹、审批、取消、幂等业务回执                     | 模拟提交不等于真实退款到账                   |
| 系统可靠性 | Workflow、SQLite、ASGI API              | 16 个故障/隔离场景 + 可配置并发 | 恢复、鉴权、重复请求、版本冲突、超时、降级、取消、错误率和延迟分位数             | 本地结果不能代表生产集群容量                 |
| 业务效果   | 导入完整客服会话结果                    | 12 条合成演示 + 空白生产模板    | 已核实解决率、首次解决、复联、必要/无效转人工、CSAT、成本与标注覆盖率            | 无真实数据时不计算“真实业务提升”           |

建议按“执行是否成功 → 路由是否正确 → 证据是否充分 → 回答是否合格 → 问题是否解决”逐层定位，不用一个总分掩盖严重问题。

### 2.1  检索质量：72 条问题，比较三种检索方式

python evaluation/run.py retrieval --mode live --allow-live --strategies hybrid bm25 vector --out evaluation/reports/live/retrieval

### 2.2  回答质量：

#### 生成知识问答和订单问答

python evaluation/run.py answers --mode live --allow-live --out evaluation/reports/live/knowledge
python evaluation/run.py answers --mode live --allow-live --dataset evaluation/data/orders.jsonl --out evaluation/reports/live/orders

#### 2.2.1 知识问答：RAGAS + Judge

python evaluation/run.py score --input evaluation/reports/live/knowledge/answers.json --judge --ragas --allow-live --out evaluation/reports/scored/knowledge

#### 2.2.2 订单问答：Judge 根据实际工具返回评审

python evaluation/run.py score --input evaluation/reports/live/orders/answers.json --judge --allow-live --out evaluation/reports/scored/orders

### 2.3  业务流程：32 个多轮场景

python evaluation/run.py workflow --mode live --allow-live --out evaluation/reports/live/workflow

### 2.4  系统可靠性：故障注入使用隔离的 offline 环境

python evaluation/run.py reliability --out evaluation/reports/offline/reliability

#### 2.4.1 补充真实模型下的进程内并发测试

python evaluation/run.py load --mode live --allow-live --requests 20 --concurrency 4 --out evaluation/reports/live/load

### 2.5 业务效果：替换为你实际导出的生产会话文件

python evaluation/run.py business --input your_sessions.jsonl --out evaluation/reports/business/production

## 3. 为什么截图里的 100% 不够

原脚本 `eval/runners/retrieval.py` 做的是：检索问题，把返回的上下文拼起来，只要其中出现该题任意关键词，就算一次命中。你的截图为 `47 / 47 = 1.0`；另外 5 条知识库无答案题不进入该比例。

它没有生成客服答案，没有判断回答事实、必要条件、引用、工具调用、审批和问题解决。代码中的指标名也明确写了 `NOT_answer_accuracy`。

新工具保留关键词代理作为回归对照，但增加必要证据标注和完整会话检查。**随包新结果是扩展后的数据集和离线模式，不能直接与截图中的 live 47/47 做性能升降比较。**

## 4. 数据集来源与标注方法


| 文件                           | 数量 | 构造方式                                                                          | 划分               |
| -------------------------------- | -----: | ----------------------------------------------------------------------------------- | -------------------- |
| `data/knowledge.jsonl`         |   72 | 原`eval/datasets/qa.jsonl` 的 52 条 + 20 条人工构造改写；62 条有答案、10 条无答案 | dev 57 / test 15   |
| `data/orders.jsonl`            |   12 | 基于项目演示订单的查询、物流、缺订单号、不存在、越权问题                          | dev 9 / test 3     |
| `data/workflows.jsonl`         |   32 | 根据项目状态机设计正常、异常、边界及多轮轨迹                                      | dev 24 / test 8    |
| `data/reliability.jsonl`       |   16 | 固定故障注入和权限/幂等场景清单                                                   | 全部 dev           |
| `data/business_demo.jsonl`     |   12 | 带`synthetic: true` 的演示会话                                                    | 仅验证统计逻辑     |
| `data/business_template.jsonl` |    0 | 留给真实导出的会话记录                                                            | 不能直接评估空文件 |
| `data/business_schema.json`    |   — | 生产记录字段说明及 JSON Schema                                                    | 配合语义校验使用   |

数据是**基于仓库整理的初始标注集**，还没有业务专家复核。不要把它称为真实用户测试集或大规模生产基准。

知识题按 `group_id` 划分，原题和对应改写保持在同一个集合。校验器检查重复 ID、证据是否存在于知识库、分组是否跨集合。不同组仍可能共享政策或知识片段，尤其是跨主题组合题；这不是完全独立的知识泛化测试。流程集的 dev/test 也是回归组织方式，不能当作独立随机样本。

后续应补充脱敏真实问题：口语、省略、错别字、多意图、规则冲突、资料过期、无答案、越权、工具失败。对同一个真实问题的多个改写采用相同 `group_id`，避免一边调参一边泄漏测试题。

### 知识题字段

```json
{
  "id": "kb-023",
  "category": "退货规则",
  "question": "无理由退货需要满足什么条件？",
  "reference": "需不影响二次销售。",
  "group_id": "退货规则",
  "split": "dev",
  "answerable": true,
  "gold_evidence": [["不影响二次销售"]],
  "required_facts": [["不影响二次销售"]],
  "expected_domain": "customer",
  "forbidden_patterns": [],
  "rubric": "依据公开知识回答；问题是规则咨询，不代表用户授权实际申请。"
}
```

`gold_evidence` 中每个内层数组表示**一个必要证据单元的可接受文本表达**：同一组内满足一个表达即可，不同组都应该覆盖。`required_facts` 用相同结构对最终回答做文本代理检查。它不能识别所有同义改写，也不能识别所有否定关系，所以不能代替事实正确率。

无答案题设置 `answerable: false`、`gold_evidence: []`，参考答案说明应有的资料边界或澄清方式。这些题交给 Judge 和人工判断拒答/澄清是否适当，不填一个伪造的 RAGAS 满分。

`build_datasets.py` 保留了可复现的构造逻辑。需要重新构造时执行：

```bash
python -m evaluation.build_datasets
python evaluation/run.py validate
```

**这会覆盖现有初始数据集。**已经人工修订过 JSONL 时，先同步修改生成脚本或保留修订版，不要直接重建丢失标注。

## 5. 检索质量：先看证据，再看排序

```bash
python evaluation/run.py retrieval --strategies hybrid bm25 vector --ks 1 3 5 --top-k 5
python evaluation/run.py retrieval --no-rerank --out evaluation/reports/latest/no_rerank
```

`hybrid` 调用项目完整 `KnowledgeService.search()`；`bm25` 和 `vector` 分别调用同一份分块索引的单路检索。单路结果不经过 Reranker。`--no-rerank` 只影响混合检索。


| 输出字段                              | 定义                                     | 用途                                 |
| --------------------------------------- | ------------------------------------------ | -------------------------------------- |
| `evidence_hit`                        | 前 K 个片段是否覆盖至少一个标注证据单元  | 发现完全漏检                         |
| `evidence_unit_recall`                | 已覆盖的必要证据单元数 / 全部必要单元数  | 发现只找到部分条件                   |
| `annotated_chunk_precision`           | 前 K 中命中标注的片段数 / 实际返回片段数 | 观察上下文噪声的代理                 |
| `mrr`                                 | 第一个命中片段排名的倒数；未命中为 0     | 判断证据是否排在前面                 |
| `keyword_proxy_hit_known`             | 有答案题中任意关键词命中的比例           | 与旧方法对照                         |
| `unknown_nonempty_retrieval`          | 无答案题仍返回片段的比例                 | 提醒需要拒答机制，不能直接称作幻觉率 |
| `degraded_queries` / `rerank_applied` | 降级查询数 / 实际执行重排的次数          | 确认测到的是预期检索路径             |

这里的召回分母是**标注证据单元**，不是全库所有相关文档；片段精度也是标注代理，不是穷尽人工相关性标注后的标准 Precision@K。当前没有伪造 nDCG：要加 nDCG，应先给候选片段标注多级相关性。

检索抛错时，该有答案题的命中/召回为 0，并保留错误；不会从分母里消失。默认报告 K=1、3、5。数据集很小，知识库默认只有 7 个片段，Top5 覆盖面很大，应关注 Top1、MRR、负例和真实新增知识后的变化。

离线向量是测试实现，离线 Reranker 不会真实调用模型。因此随包的 BM25/向量对比是实现回归，不用于选择生产 Embedding 模型。

## 6. 回答质量：实际答案 + 实际上下文 + 独立评分

`answers` 为每道题建立独立会话，调用 `WorkflowService.events()`，让 SupportGraph 自行路由和调用工具。`observe.py` 通过 LangChain callbacks 捕获实际工具名、参数、工具结果、模型 usage 和事件。

**RAGAS 使用的是本次 `search_knowledge` 工具返回给 Agent 的 contexts，不会另做一次检索补证据。**路由错误导致没有搜索时，该题的缺失证据会保留，不能用事后检索得到的片段掩盖问题。

先运行 live 答案生成。根目录 `.env` 使用项目原有的 `AIROBOT_LLM_*`、`AIROBOT_EMBEDDING_*`、`AIROBOT_RERANK_*` 配置：

```bash
python evaluation/run.py answers --mode live --allow-live --limit 5 --out evaluation/reports/live/pilot
```

评估器强制使用临时 SQLite、本地向量索引和关闭的响应缓存；不会把根目录 `.env` 的生产数据库、Redis、Milvus 配置带进来。临时数据在结束时清理；报告留下可检查轨迹。这样做可以评估真实模型行为，但不能宣称覆盖了生产后端集成。

### 6.1 安装语义评分依赖

```bash
python -m pip install -r evaluation/requirements-ragas.txt
python -m pip check
python -m pytest evaluation/tests/test_ragas_adapter.py -q
```

已测试组合：RAGAS 0.4.3、langchain-community 0.3.31、Instructor 1.17.0、OpenAI Python 2.54.0。RAGAS 0.4.3 启动时会导入 community 中的旧 VertexAI 模块，而 community 0.4.2 已移除该模块；因此固定兼容版本。完整关键版本记录在 `TESTED_VERSIONS.txt`。

复制 `evaluation/.env.eval.example` 为 `evaluation/.env.eval`，填入独立评审模型和评分用 Embedding 配置。环境变量中的 `EVAL_*` 会覆盖此文件。评估器不会默默复用被测模型的密钥。

```dotenv
EVAL_JUDGE_BASE_URL=你的兼容OpenAI接口的v1地址
EVAL_JUDGE_API_KEY=你的评审模型密钥
EVAL_JUDGE_MODEL=你的评审模型名
EVAL_EMBEDDING_BASE_URL=你的Embedding接口v1地址
EVAL_EMBEDDING_API_KEY=你的Embedding密钥
EVAL_EMBEDDING_MODEL=你的Embedding模型名
```

评审接口需要支持 `response_format: json_object`。本包验证的 RAGAS 适配器也使用 JSON mode。选择能稳定处理中文客服事实、条件和拒答的模型，并先检查小批量输出。尽量用独立于被测模型的评审配置；同一模型会记录 `judge_same_model_as_generator: true`，供分析自评偏差。

### 6.2 对已生成报告打分

```bash
python evaluation/run.py score --input evaluation/reports/live/pilot/answers.json --judge --ragas --allow-live --out evaluation/reports/scored/pilot
```

它只评分已有答案，**不会再次调用客服生成答案**。可以单独用 `--judge` 或 `--ragas`，可以加 `--limit 5`、`--timeout 120`。`--timeout` 是每个 Judge/单项指标任务的秒数上限；一条样本有多个指标，所以不是全报告总时限。

默认拒绝给 offline 脚本答案做付费评分。若确实要验证评分接线，需额外加 `--allow-fixture-score`；这依然只是模拟答案的评分。RAGAS 一项可能内部多次请求，不能把“5 个样本”理解为“5 次 API 请求”。


| RAGAS 指标        | 检查什么                           | 需要的数据                       |
| ------------------- | ------------------------------------ | ---------------------------------- |
| Faithfulness      | 回答中的事实是否有检索内容支持     | 问题、回答、实际 contexts        |
| Answer Relevancy  | 回答是否围绕问题                   | 问题、回答；评分模型和 Embedding |
| Context Precision | 有助于参考答案的上下文是否排在前面 | 问题、reference、实际 contexts   |
| Context Recall    | 参考答案中的事实是否被上下文覆盖   | 问题、reference、实际 contexts   |

实现使用 `ragas.metrics.collections` 的新接口。指标含义见官方 [Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)、[Response Relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/)、[Context Precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/)、[Context Recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/) 文档。这里的 RAGAS Context Precision 是排序相关的平均精度，和上一节的文本标注片段精度不是同一个指标。

RAGAS 只用于**有答案的知识问答**。无答案题和订单题记录 `not_applicable`。有答案知识题若缺少实际 contexts，需要上下文的指标记录 `blocked`，仍留在适用样本分母中；Answer Relevancy 可以单独评分。超时、JSON 格式错误、NaN 等记录 `error`，并展示每个指标的评分覆盖率，不能当作 0 分或 1 分混入均值。

### 6.3 Judge、文本代理与人工如何分工

Judge 读取问题、最终回答、reference、rubric、实际工具参数及返回，分别输出：

- `correctness`：事实、金额、状态、规则是否正确，1–5 分。
- `completeness`：条件、限制、操作步骤是否完整，1–5 分。
- `relevance`：是否回答当前问题，1–5 分。
- `groundedness`：是否有证据，是否虚构操作完成，1–5 分。
- `critical_error`：是否泄露他人资料、绕过审批、虚构退款或重要政策。
- `explanation`：便于复核的简要依据。

使用 Pydantic 严格校验，非法分数、字符串冒充数值、无效 JSON 都会记失败。示例 `rubric_pass` 定义为四项均至少 4 分且无严重错误，**这是本包的起始量表，不是行业统一门槛，也不自动代表可上线**。

自动文本断言负责发现明确遗漏和禁用表达；它们的 `fact_coverage_proxy` 只作辅助。原始 `answers.json` 中的 `routing_and_tool_rule_pass` 也只代表路由和调用约束。即使 Judge 已经评分，原来的 `passed` 字段仍是规则结果，语义结论看 `judge`/`ragas`。

订单题主要按订单工具结果评审，不能拿一篇公开知识文档来评价订单事实。无答案题重点评价是否如实说明边界、是否合理澄清，不能因为没有知识库答案就处罚正确拒答。

导出人工盲评表：

```bash
python evaluation/run.py review --input evaluation/reports/scored/pilot/score.json --out evaluation/reports/review/pilot
```

生成 UTF-8 BOM 的 `human_review.csv`，包含问题、答案、参考、上下文和工具结果；人工分数留空，表中不显示 Judge 的评分。可用 Excel 打开。先抽样复核全部严重错误、无答案、越权、路由错误和少量随机通过样本；再用同一量表比较人机一致性及“人工判失败而 Judge 放行”的漏检情况。当前提供盲评导出，不自动导入人工表或计算 Cohen's kappa。

## 7. 业务流程：评价完成任务所需的动作和状态

```bash
python evaluation/run.py workflow --out evaluation/reports/latest/workflow
python evaluation/run.py workflow --mode live --allow-live --split dev --repeats 3 --out evaluation/reports/live/workflow
```

每个场景拥有独立 SQLite 和会话；场景内部多轮共享状态。`restart` 会关闭并重新创建容器，使用同一个数据目录恢复 checkpoint；它测试应用重建，不是强杀进程或断电。

32 个场景覆盖：普通咨询、订单追问和领域切换；低风险申请；等待确认；高风险同意/拒绝；超期、损坏、使用过、运输中；取消；缺订单号/商品状态；人工接管/补充信息；审批后重启恢复；重复 chat/resume；切换订单；未支付、已退款、特殊类目；金额阈值两侧；跨用户访问；更换订单后清除旧确认。

例如高金额申请必须先等待客户确认，再等待人工审批，审批前不能有业务提交：

```json
{
  "id": "wf07",
  "category": "high_approval",
  "risk": "critical",
  "split": "dev",
  "turns": [
    {"action": "chat", "message": "订单202609140002我要退货，不想要了，商品未使用",
     "expect": {"case.status": "awaiting_confirmation"}},
    {"action": "chat", "message": "确认提交",
     "expect": {"waiting_human": true}, "expect_operations": 0},
    {"action": "resume", "decision": "approve", "message": "已核实，同意模拟申请",
     "expect": {"case.status": "completed"}, "expect_operations": 1}
  ]
}
```

支持的断言：


| 字段                                    | 检查内容                                                        |
| ----------------------------------------- | ----------------------------------------------------------------- |
| `expect`                                | 返回字段、嵌套状态；数组表示可接受值集合                        |
| `required_tools` / `tool_args`          | 实际调用必要工具，并核对业务参数                                |
| `forbidden_tools`                       | 出现过禁止工具调用就失败，即使工具最后报错                      |
| `ordered_tools`                         | 必要工具的先后次序，允许穿插其他合法调用                        |
| `forbidden_stages`                      | 不应重复进入的阶段，例如同域追问重新 triage                     |
| `expect_operations`                     | SQLite`operations` 中的模拟业务回执数，检查未授权写入和重复提交 |
| `required_facts` / `forbidden_patterns` | 回复的文本代理约束                                              |

只有本场景所有断言成立才算任务成功。报告按场景分类，同时单列 `critical_case_failures`。不会因为其他普通问题通过较多就掩盖一个越权或审批错误。

流程断言应由业务政策定义。当前项目的 `case.status=completed` 与一条模拟回执不代表订单真的变为“退款到账”；这套用例不会做这种推断。

## 8. 系统可靠性：故障注入与并发分别看

```bash
python evaluation/run.py reliability --fail-on-regression
python evaluation/run.py load --requests 100 --concurrency 8 --out evaluation/reports/latest/load_100
```

可靠性故障集强制 `offline`，不会主动攻击生产接口。真实执行 Graph/SQLite/ASGI，本地 MockTransport 模拟上游 HTTP。


| 场景 ID                 | 断言                                                                  |
| ------------------------- | ----------------------------------------------------------------------- |
| `request_replay`        | 相同请求号返回回放结果，不重复追加消息                                |
| `request_conflict`      | 相同请求号携带不同内容应冲突                                          |
| `lease_conflict`        | 同一会话互斥，并在结束后释放                                          |
| `operation_idempotency` | 相同业务指纹只提交一次，不同指纹冲突                                  |
| `session_isolation`     | 其他用户不能读写本用户会话                                            |
| `api_identity`          | 请求体不能伪造身份，普通用户不能访问管理入口                          |
| `approval_auth`         | 客户端身份不能代替员工审批                                            |
| `checkpoint_restart`    | 容器重建后恢复审批，只生成一条业务回执                                |
| `vector_failure`        | 向量检索失败后 BM25 可用，并显式标记降级                              |
| `rerank_failure`        | 重排上游失败后保留回退顺序，记录失败原因                              |
| `agent_timeout`         | Agent 异常应记录技术失败，不错误创建业务人工工单                      |
| `tool_failure`          | 订单工具失败不编造查询成功，不产生业务写入                            |
| `ticket_version`        | 工单旧版本更新应冲突                                                  |
| `http_retry`            | 可重试错误会重试；401 不盲目重试                                      |
| `cache_generation`      | 增删知识文档改变索引 generation；验证代际变化，不等于完整缓存集成测试 |
| `client_cancel`         | 取消请求后记录失败、释放锁、不产生业务写入                            |

`load` 测试的是**进程内 WorkflowService、多个独立会话**，输出成功率、P50/P95/P99、完成吞吐量；包括会话执行耗时，不包含真实网络、负载均衡或浏览器 SSE 开销，也没有预热阶段。它适合发现本地并发错误，不是生产 SLA 或机器选型数据。

上线前仍应在隔离的预发布环境补充：实际 HTTP/SSE、用户断连、长时间运行、数据库断连/进程强杀、外部依赖、生产规模索引和真实后端。当前未测 Redis/Milvus/PostgreSQL 集群恢复；也未伪造这些集成结果。

## 9. 业务效果：必须来自真实结果，而不是客服自述

演示统计与真实统计使用同一个聚合器，区别在于来源。`business_demo.jsonl` 明确标记 `synthetic: true`，不加 `--demo` 会拒绝使用。

真实记录一行一个 JSON 对象，字段示意：

```json
{"session_id":"s-real-001","customer_hash":"hash-customer-1","issue_id":"issue-001","category":"after_sales","started_at":"2026-09-10T08:00:00Z","ended_at":"2026-09-10T08:05:00Z","resolved":true,"resolution_source":"business_receipt","handoff":false,"handoff_required":false,"csat":null,"technical_failure":false,"latency_ms":1800,"cost_usd":0.012,"synthetic":false}
```

这只是字段示意，不能直接作为真实生产样本。`resolved` 必须有顾客确认、业务回执或人工复核证据；模型说“已解决”不算。暂不清楚就填 `null`，并填 `resolution_source: "unknown"`。

`resolution_source` 支持 `customer_confirmed`、`business_receipt`、`human_review`、`unknown`。已有明确成功/失败标签时，不能把来源填成 `unknown`。`handoff_required` 是业务必要性标注，不等于系统有没有转人工。`cost_usd` 应由真实账单/计费规则汇总，缺失填 `null`，不能填 0 冒充免费。

时间必须含时区。校验会拒绝重复会话 ID、非法评分、负数或非有限成本、结束早于开始等记录。用稳定脱敏 `customer_hash`，同一问题跨渠道、跨会话复联必须沿用相同 `issue_id`。

```bash
python evaluation/run.py business --input your_sessions.jsonl --as-of 2026-09-16T00:00:00Z --window-hours 48 --out evaluation/reports/business/20260916
```


| 指标               | 明确分母/定义                                               |
| -------------------- | ------------------------------------------------------------- |
| 已核实解决率       | 明确解决的会话 / 有明确解决或未解决标签的会话               |
| 结果标注覆盖率     | 有明确结果标签的会话 / 全部会话                             |
| 全量已核实解决下界 | 明确解决的会话 / 全部会话；未知不会算成功                   |
| 转人工率           | 转人工会话 / 全部会话；单独高低不代表好坏                   |
| 必要转人工召回     | 需要转人工且实际转了 / 标注需要转人工                       |
| 无效转人工率       | 不需要转人工却转了 / 标注不需要转人工                       |
| CSAT 均值与响应率  | 有反馈的 1–5 分均值；有反馈会话 / 全部会话                 |
| 技术失败率与覆盖率 | 失败数 / 已知技术状态数，同时展示状态已知比例               |
| 复联率             | 首次会话结束后窗口内发生同问题复联的成熟首访 / 全部成熟首访 |
| 首次已核实解决率   | 首次已核实解决且窗口内无复联 / 全部成熟首访                 |
| AI 独立首次解决率  | 上述条件再加首次未转人工 / 全部成熟首访                     |
| 单次已核实解决成本 | 全部会话成本 / 已核实解决数；成本缺失或无解决样本时为 null  |

“成熟首访”表示从首次会话结束到 `as-of` 已经过完整观察窗口，默认 48 小时。窗口未满者不进入复联/首次解决分母；该窗口只是可配置的起点，应按业务服务周期调整。

导出必须覆盖首访和后续联系，否则会高估首次解决。若只导出某一渠道或只保留成功案例，统计口径会失真。解决率和成本按会话统计，复联/首次解决按 `customer_hash + issue_id` 分组；不能把它们的分母混为一谈。

生产结果不由本包自动从聊天文本推断，也不会自动从现有 SQLite 的模拟订单生成。只有接入真实客服工单/业务回执/反馈导出后，才能讨论减少人工和提升解决率。

## 10. 版本比较与上线使用方式

```bash
# 两份报告必须来自相同数据集、知识库版本、模式、K 和样本选择
python evaluation/run.py compare --baseline evaluation/reports/baseline/answers.json --candidate evaluation/reports/candidate/answers.json --out evaluation/reports/compare/run1
```

支持 `retrieval/answers/workflow/reliability/score` 的配对比较。要求同一组 ID、repeat、strategy；不同数据集、样本缺失或重复键会拒绝比较。对 `score` 还要求相同评审模型、提示词和评分选项。代码/被测模型配置可以改变，原始元数据都会保留。

比较报告展示数值差异、规则由通过变失败的样本、严重流程回归和新执行错误。它是描述性对比，**没有自动计算统计显著性**。多个改写或同题多次运行彼此相关，不应把它们当作独立用户扩大样本量。报告会同时提供 paired rows 与 unique cases。

建议在生产研发中这样使用：

1. **每次代码修改：**运行数据校验、原项目测试、可靠性集、流程集、关键问答；优先阻断越权、重复写入、绕过审批等严重回归。
2. **每次模型/提示词/检索配置修改：**固定数据与知识库，在 dev 集调试；再跑冻结的 test 集和同一套 Judge/RAGAS，结合标注覆盖率检查差异。
3. **候选版本评审：**人工复核全部严重异常、所有关键业务流程以及分层抽样答案，确定业务可接受的阈值；不要直接把本包的 4 分量表当发布标准。
4. **预发布：**接入真实部署后端进行故障恢复与 HTTP/SSE 负载测试，依据真实延迟/成本目标决定容量。
5. **上线后：**按用户/问题类别比较有完整观察窗口的业务结果，监控新增失败类型，将经复核案例加入下次回归。讨论因果提升时需要合理的对照或 A/B 分流，不能仅比较前后两个平均数。

阈值应来自业务风险、基线和人工验收。初始数据集只有少量政策和模拟场景，不能证明“零事故”。

## 11. 随包运行结果：成绩与限制一起保留

`reports/offline/` 包含已实际运行的报告，均为 offline，本轮未调用任何付费生成/Embedding/Judge API。


| 项目                   | 实际结果                    | 解读                                                                                                        |
| ------------------------ | ----------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 项目原有自动化测试     | 57 通过                     | 原有测试在当前依赖组合下通过                                                                                |
| 新增评估测试           | 24 通过                     | 覆盖指标数学、缺失分母、隐私调用、隔离、业务窗口、评分失败及真实 RAGAS 适配器；上游 HTTP 使用 MockTransport |
| 知识问答执行           | 72/72 成功执行              | 不代表都回答正确                                                                                            |
| 知识问答路由/工具规则  | 66/72 通过                  | 6 条路由断言失败，见下表                                                                                    |
| 订单问答规则           | 12/12 通过                  | 模拟订单；未做真实 Judge 语义验收                                                                           |
| 多轮流程               | 32/32 通过                  | 离线规则模型与模拟业务下通过                                                                                |
| 可靠性场景             | 16/16 通过                  | 当前本地隔离范围内通过                                                                                      |
| 混合检索证据 Hit@5     | 59/62，约 95.16%            | 初始证据标注上的离线代理                                                                                    |
| 混合检索证据 Hit@1     | 56/62，约 90.32%            | 仍有首位证据排序问题                                                                                        |
| 本地并发               | 20 请求、并发 4，20/20 完成 | 不作为生产吞吐和 SLA 结论                                                                                   |
| RAGAS / Judge 真实评分 | 未执行                      | 已验证接口与失败处理，等待配置真实评审模型                                                                  |
| 生产业务效果           | 无真实样本                  | 附 12 条合成演示，不能宣传业务提升                                                                          |

6 条失败样本：


| ID       | 问题                     | 离线实际行为              | 应复核的差异                     |
| ---------- | -------------------------- | --------------------------- | ---------------------------------- |
| kb-017   | 提交订单前需要确认什么？ | 进入订单查询并列出订单    | 参考答案是确认收货地址           |
| kb-019   | 下单后多久发货？         | 进入订单查询并要求订单号  | 公开知识没有固定时限，应说明边界 |
| kb-025   | 怎么申请退货？           | 进入售后并要求订单号/原因 | 该题标注目标是介绍操作步骤       |
| kb-027   | 申请退货需要上传凭证吗？ | 进入售后并要求订单号/原因 | 没有回答是否需要凭证             |
| kb-052   | 不想要了退货，运费谁出？ | 进入售后并要求订单号/原因 | 没有回答个人原因运费归属         |
| para-019 | 卖家保证几小时之内发货？ | 进入订单查询并要求订单号  | 不应编造固定发货承诺，应说明边界 |

这些是**初始标注下的离线问题**。它们提示“规则咨询”和“授权办理”需要区分，但不能据此断言 live LLM 也有相同缺陷。修改路由前应复核业务期望，并用 live 数据重测。

## 12. 按文件阅读实现


| 文件                | 阅读重点                                                  |
| --------------------- | ----------------------------------------------------------- |
| `run.py`            | CLI 参数校验、子命令分发、退出码；先从这里读              |
| `common.py`         | 临时配置隔离、JSONL、指纹、分位数、报告输出               |
| `build_datasets.py` | 从仓库问题/政策构造初始知识、订单、流程、故障与业务演示集 |
| `validate.py`       | ID、证据存在性、分组与场景动作校验                        |
| `metrics.py`        | 证据匹配、文本事实代理、状态/工具参数/顺序断言            |
| `observe.py`        | callbacks 和 ContextVar 跟踪每次实际调用；不事后补检索    |
| `runners.py`        | 检索、单轮答案、多轮流程、进程内并发                      |
| `reliability.py`    | 故障注入、API 隔离、重建恢复、取消等 16 个场景            |
| `scoring.py`        | 独立 Judge、RAGAS collections 适配、适用范围与覆盖率      |
| `business.py`       | 显式业务结果校验、成熟观察窗口、解决率与成本聚合          |
| `reporting.py`      | 配对比较、人工盲评 CSV 导出                               |
| `tests/`            | 指标、统计、隔离、评分适配器的回归测试                    |

与项目源码的对应阅读顺序：`bootstrap.py` 了解容器；`workflow.py` 了解请求/会话和恢复；`graph/` 了解路由及售后状态；`agents/` 了解 Agent 调用；`services/knowledge.py` 和 `rag/` 了解检索；最后看 `storage/`、`api/` 的持久化与鉴权。评估记录正是沿着这些实际入口采集。

## 13. 常见问题

**出现 `ragas` / `langchain_community.chat_models.vertexai` 导入错误？**

使用 `requirements-ragas.txt` 的固定组合，再运行 `pip check` 和适配器测试，不要只升级其中一个包。

**检索接近满分，为什么回答仍失败？**

可能是路由没走知识 Agent、回答遗漏必要条件或无答案场景处理错误。按 `result.domain → tool_calls → contexts → answer → judge` 检查同一条记录。

**为什么有 null？**

分母为 0、缺真实标签、评分失败、指标不适用或成本不完整时，null 比伪造的 0/1 更准确。先看 coverage、status 和 reason。

**API 失败后程序返回 0 是否表示通过？**

默认退出码只表示报告成功产生。自动化规则门禁加 `--fail-on-regression`；评分覆盖率、业务指标和语义门槛仍需看报告。`score` 不提供自动发布批准。

**能否用现有线上数据库直接跑这些场景？**

当前运行器强制本地隔离，业务和订单是模拟的。真实线上会话采用 `business --input` 导入脱敏结果；预发布集成测试需另接隔离后端，不能把写入场景对准真实客户订单。

**哪些信息会进入报告？**

问题、答案、工具参数和返回、检索片段、状态、耗时及可用的 token usage；配置只记录白名单字段和指纹，不写 API 密钥，不存模型推理内容。真实数据报告可能包含业务信息，请按客服数据权限管理；调用外部 Judge 会发送所选样本的答案和证据。

模型 callbacks 没有提供 usage 时保留 null。工具包没有把测试 token 用量伪换算成生产账单，也未完整采集 RAGAS 内部请求总成本。业务成本字段应来自你自己的真实计费记录。
