"""Read-only local configuration/dependency checks; never opens external connections."""
import importlib.metadata as meta
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));os.chdir(ROOT)
PACKAGES=['langchain','langgraph','langchain-core','langchain-openai','langgraph-checkpoint',
          'langgraph-checkpoint-sqlite','fastapi','httpx','redis']
if __name__=='__main__':
    missing=[]
    for name in PACKAGES:
        try:print(f'{name}=={meta.version(name)}')
        except meta.PackageNotFoundError:print(f'{name}: MISSING');missing.append(name)
    try:
        from retrade_agent.config import Settings
        s=Settings();print(json.dumps(s.public_info(),ensure_ascii=False,indent=2))
        if s.app_mode=='offline':print('Offline fixture model: no remote inference, no paid API requests.')
        elif s.rerank_enabled and not s.rerank_api_key.get_secret_value():
            print('WARNING: reranker key missing: retrieval will report an RRF-only fallback.')
        if s.storage_backend=='postgres':print('ERROR: business PostgreSQL adapter is an integration port, not implemented.')
        if s.vector_store=='milvus':print('Check your Docker mapped Milvus port locally; 19530 is default, custom 1953 must match.')
    except Exception as exc:
        print('Configuration error: '+type(exc).__name__+'; inspect .env locally. No secret values printed.')
        sys.exit(1)
    sys.exit(1 if missing else 0)
