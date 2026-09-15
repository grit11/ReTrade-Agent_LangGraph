import asyncio
import hashlib
from pathlib import Path
from retrade_agent.errors import AppError, Unavailable
from retrade_agent.rag.loader import parse_document
from retrade_agent.rag.splitter import split_text
from retrade_agent.rag.schemas import Chunk

class KnowledgeService:
    def __init__(self,settings,repo,retriever,embeddings):
        self.settings=settings;self.repo=repo;self.retriever=retriever;self.embeddings=embeddings
        self.lock=asyncio.Lock();self.last_error=None
    async def initialize(self,seed_dir:Path):
        if not await self.repo.knowledge():
            for path in sorted(seed_dir.glob('*.md')):
                await self.ingest(path.name,path.read_bytes())
        else:
            await self.rebuild()
    async def rebuild(self):
        documents=await self.repo.knowledge();chunks=[]
        for d in documents:
            if d['embedding_signature']!=self.embeddings.signature:
                cs=split_text(d['title'],d['text'],self.settings.chunk_size,self.settings.chunk_overlap)
                vv=await self.embeddings.embed([c.text for c in cs])
                for c,v in zip(cs,vv):c.vector=v
                d.update(chunks=[c.model_dump() for c in cs],embedding_signature=self.embeddings.signature)
                await self.repo.put_document(d)
            chunks.extend(Chunk.model_validate(c) for c in d['chunks'])
        generation=hashlib.sha256(('|'.join(sorted(c.chunk_id for c in chunks))+'|'+self.embeddings.signature).encode()).hexdigest()[:24]
        await self.retriever.rebuild(chunks,generation)
        self.last_error=None
    async def ingest(self,filename,raw):
        if len(raw)>self.settings.max_upload_mb*1024*1024:raise AppError('文件超过上传限制')
        title=Path(filename.replace('\\','/')).name.strip()
        if not title or len(title)>120:raise AppError('文件名不合法或过长')
        text=await asyncio.to_thread(parse_document,title,raw)
        revision=hashlib.sha256(text.encode()).hexdigest()
        async with self.lock:
            for d in await self.repo.knowledge():
                if d['title']==title and d['revision']==revision and d['embedding_signature']==self.embeddings.signature:
                    await self.rebuild()
                    return {'document_id':d['document_id'],'chunks':len(d['chunks']),'deduplicated':True}
            chunks=split_text(title,text,self.settings.chunk_size,self.settings.chunk_overlap)
            vectors=await self.embeddings.embed([c.text for c in chunks])
            for c,v in zip(chunks,vectors):c.vector=v
            doc_id=hashlib.sha256(title.encode()).hexdigest()[:24]
            doc={'document_id':doc_id,'title':title,'text':text,'revision':revision,
                 'embedding_signature':self.embeddings.signature,'chunks':[c.model_dump() for c in chunks]}
            await self.repo.put_document(doc)
            try:await self.rebuild()
            except Exception as exc:
                self.last_error=type(exc).__name__
                raise
            return {'document_id':doc_id,'chunks':len(chunks),'deduplicated':False}
    async def search(self,query,top_k=None):
        async with self.lock:
            if self.last_error:
                raise Unavailable('知识索引尚未就绪，请由管理员重建后再查询')
            return await self.retriever.search(query,top_k)
    async def list_documents(self):
        return [{'document_id':d['document_id'],'title':d['title'],'revision':d['revision'][:12],
                 'chunk_count':len(d['chunks']), 'updated_at':d.get('updated_at')} for d in await self.repo.knowledge()]
    async def remove(self,document_id):
        async with self.lock:
            await self.repo.delete_document(document_id)
            try:
                await self.rebuild()
            except Exception as exc:
                self.last_error=type(exc).__name__
                raise
