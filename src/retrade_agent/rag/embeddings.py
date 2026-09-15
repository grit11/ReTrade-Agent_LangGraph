import hashlib
import math
import httpx
from retrade_agent.rag.bm25 import tokenize
from retrade_agent.storage.clients import request_json

class EmbeddingClient:
    def __init__(self,settings):
        self.settings=settings
        self.http=httpx.AsyncClient(timeout=settings.llm_timeout)
        self.signature=('offline-bigram-192-v1' if settings.app_mode=='offline' else
                        f'{settings.embedding_base_url}|{settings.embedding_model}')
    async def embed(self,texts:list[str])->list[list[float]]:
        if not texts:return []
        if self.settings.app_mode=='offline':
            result=[]
            for text in texts:
                v=[0.0]*192
                for t in tokenize(text):v[int(hashlib.sha256(t.encode()).hexdigest()[:8],16)%192]+=1
                norm=math.sqrt(sum(x*x for x in v)) or 1
                result.append([x/norm for x in v])
            return result
        out=[]
        for start in range(0,len(texts),16):
            batch=texts[start:start+16]
            data=await request_json(self.http,self.settings.embedding_base_url.rstrip('/')+'/embeddings',
                self.settings.embedding_api_key.get_secret_value(),{'model':self.settings.embedding_model,'input':batch})
            items=sorted(data['data'],key=lambda x:x['index'])
            if [r['index'] for r in items]!=list(range(len(batch))):raise ValueError('Embedding response indices mismatch')
            vectors=[r['embedding'] for r in items]
            if not vectors or any(not v or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v) for v in vectors):
                raise ValueError('Invalid embeddings')
            if len({len(v) for v in vectors})!=1:raise ValueError('Embedding dimensions differ')
            out.extend(vectors)
        return out
    async def close(self):await self.http.aclose()
