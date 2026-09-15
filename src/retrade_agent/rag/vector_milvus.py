"""Native PyMilvus adapter, independent of old langchain-milvus versions.
A dedicated collection + active generation isolates this project and stale chunks.
"""
import asyncio
import re
from retrade_agent.errors import ConfigurationError
class MilvusVectors:
    def __init__(self,settings):
        self.settings=settings;self.client=None
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',settings.milvus_collection):
            raise ConfigurationError('Milvus collection 名称不合法')
    def _client(self):
        if self.client is None:
            try:from pymilvus import MilvusClient
            except ImportError as exc:raise ConfigurationError('请安装 pip install -e ".[milvus]"') from exc
            self.client=MilvusClient(uri=self.settings.milvus_uri,token=self.settings.milvus_token.get_secret_value(),timeout=10)
        return self.client
    async def synchronize(self,chunks,generation):
        if not chunks:return
        def write():
            c=self._client();name=self.settings.milvus_collection;dim=len(chunks[0].vector)
            if not c.has_collection(name):
                c.create_collection(collection_name=name,dimension=dim,id_type='string',max_length=128,
                                    primary_field_name='id',vector_field_name='vector',auto_id=False,
                                    metric_type='COSINE',enable_dynamic_field=True,consistency_level='Strong')
            fields=c.describe_collection(name).get('fields',[])
            for f in fields:
                if f.get('name')=='vector' and int(f.get('params',{}).get('dim',dim))!=dim:
                    raise ConfigurationError('向量维度不一致，请使用新 collection，不要清空旧数据')
            for start in range(0,len(chunks),128):
                rows=[{'id':x.chunk_id,'vector':x.vector,'generation':generation} for x in chunks[start:start+128]]
                c.upsert(collection_name=name,data=rows)
        await asyncio.to_thread(write)
    async def search(self,vector,k,generation):
        if not re.fullmatch(r'[a-f0-9]+',generation):raise ValueError('invalid generation')
        def search():
            rows=self._client().search(collection_name=self.settings.milvus_collection,data=[vector],
                limit=k,filter=f'generation == "{generation}"',output_fields=['id'])
            return [(str(x['id']),float(x['distance'])) for x in rows[0]] if rows else []
        return await asyncio.to_thread(search)
    async def close(self):
        if self.client:await asyncio.to_thread(self.client.close)
