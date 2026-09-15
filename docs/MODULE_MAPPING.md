# 目录重构映射

- `core/*` -> 顶层 `config.py/errors.py/llm.py/text.py`
- `domain/*` -> `models.py` + `storage/contracts.py`
- `graph/agents/*` -> `agents/*`
- `graph/parent/*` -> `graph/support.py` + `graph/state.py`
- `graph/subgraphs/after_sales/*` -> `graph/after_sales.py`
- `rag/ingestion|retrieval|rerank/*` -> `rag/*.py`
- `infrastructure/*` -> `storage/*.py` 或 `rag/*.py`
- `application/*` -> `bootstrap.py` + `workflow.py`
