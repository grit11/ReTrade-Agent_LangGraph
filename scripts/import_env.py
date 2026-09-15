"""Import LOCAL credentials; no secrets are echoed or fetched from GitHub.
python scripts/import_env.py --source ../ReTrade_V2/.env --force
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ALLOWED={
 'AIROBOT_LLM_BASE_URL','AIROBOT_LLM_API_KEY','AIROBOT_LLM_MODEL',
 'AIROBOT_LLM_TEMPERATURE','AIROBOT_LLM_TIMEOUT','AIROBOT_LLM_EXTRA_BODY',
 'AIROBOT_STRUCTURED_OUTPUT_METHOD','AIROBOT_EMBEDDING_BASE_URL',
 'AIROBOT_EMBEDDING_API_KEY','AIROBOT_EMBEDDING_MODEL','AIROBOT_RERANK_ENABLED',
 'AIROBOT_RERANK_BASE_URL','AIROBOT_RERANK_API_KEY','AIROBOT_RERANK_MODEL',
 'AIROBOT_RERANK_TIMEOUT','SILICONFLOW_API_KEY','AIROBOT_VECTOR_STORE',
 'AIROBOT_MILVUS_URI','AIROBOT_MILVUS_TOKEN','AIROBOT_TOP_K','AIROBOT_CHUNK_SIZE',
 'AIROBOT_CHUNK_OVERLAP','AIROBOT_HYBRID_VECTOR_TOP_K','AIROBOT_HYBRID_BM25_TOP_K',
 'AIROBOT_HYBRID_FUSION_TOP_K','AIROBOT_CACHE_ENABLED','AIROBOT_RATELIMIT_PER_MINUTE',
 'REDIS_URL',
}

def migrate(source:Path,destination:Path,force=False,mode='live'):
    from dotenv import dotenv_values
    if not source.is_file():raise ValueError('Source .env does not exist')
    if source.resolve()==destination.resolve():raise ValueError('Source and destination must differ')
    if destination.exists() and not force:raise ValueError('Destination exists; use --force after checking it')
    # dotenv does not interpolate: a literal secret containing $ must stay literal.
    source_data=dotenv_values(source,encoding='utf-8-sig',interpolate=False)
    target=dotenv_values(ROOT/'.env.example',encoding='utf-8-sig',interpolate=False)
    changed=[]
    for k,v in source_data.items():
        if k in ALLOWED and v is not None:target[k]=v;changed.append(k)
    if not target.get('AIROBOT_RERANK_API_KEY') and source_data.get('SILICONFLOW_API_KEY'):
        target['AIROBOT_RERANK_API_KEY']=source_data['SILICONFLOW_API_KEY']
    target.update(APP_MODE=mode,STORAGE_BACKEND='sqlite',CHECKPOINT_BACKEND='sqlite',
        AIROBOT_MILVUS_COLLECTION='retrade_langgraph_kb',AIROBOT_MILVUS_RESET_ON_START='false',
        AIROBOT_RERANK_PROVIDER='siliconflow',ASYNC_DATABASE_URL='',LANGGRAPH_DATABASE_URL='')
    if target.get('AIROBOT_RERANK_MODEL')=='BAAI/bge-reranker-base':
        target['AIROBOT_RERANK_MODEL']='BAAI/bge-reranker-v2-m3'
    if target.get('AIROBOT_VECTOR_STORE')=='inmemory':target['AIROBOT_VECTOR_STORE']='local'
    if destination.exists():shutil.copy2(destination,destination.with_name('.env.backup'))
    def quote(v):return "'"+str(v).replace('\\','\\\\').replace("'","\\'")+"'"
    destination.write_text('# LOCAL SECRETS: never commit this file\n'+''.join(f'{k}={quote(v or "")}\n' for k,v in target.items()),encoding='utf-8')
    try:os.chmod(destination,0o600)
    except OSError:pass
    return sorted(changed)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--destination',type=Path,default=ROOT/'.env')
    p.add_argument('--force',action='store_true')
    p.add_argument('--mode',choices=['live','offline'],default='live')
    a=p.parse_args()
    try:names=migrate(a.source,a.destination,a.force,a.mode)
    except (ValueError,ImportError) as exc:raise SystemExit(str(exc))
    print('Imported configuration keys (values are hidden): '+', '.join(names))
    print('Separate collection, SQLite storage, remote reranker. Run: python scripts/doctor.py')
