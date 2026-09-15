import time
from retrade_agent.rag.schemas import RetrievalResult
from retrade_agent.rag.bm25 import BM25
from retrade_agent.rag.fusion import reciprocal_rank_fusion

class HybridRetriever:
    def __init__(self,settings,embeddings,vectors,reranker):
        self.settings=settings;self.embeddings=embeddings;self.vectors=vectors;self.reranker=reranker
        self.chunks=[];self.generation='0';self.bm25=BM25([]);self.vector_ready=False
    async def rebuild(self,chunks,generation):
        # Publish the new snapshot only after remote vectors are synchronized.
        await self.vectors.synchronize(chunks,generation)
        self.chunks=list(chunks);self.generation=generation
        self.bm25=BM25([c.text for c in chunks]);self.vector_ready=True
    async def search(self,query,top_k=None):
        start=time.perf_counter();s=self.settings;top_k=top_k or s.top_k
        if not self.chunks:return RetrievalResult(detail={'reason':'empty_knowledge'})
        chunks=self.chunks;bm25=self.bm25;generation=self.generation
        by_id={c.chunk_id:c for c in chunks};detail={'generation':generation,'hybrid':True}
        t=time.perf_counter();lexical=bm25.search(query,s.bm25_k)
        detail.update(bm25_ms=round((time.perf_counter()-t)*1000,2),bm25_hits=len(lexical))
        t=time.perf_counter();dense=[]
        try:
            vec=(await self.embeddings.embed([query]))[0]
            dense=await self.vectors.search(vec,s.vector_k,generation)
        except Exception as exc:detail.update(vector_error=type(exc).__name__,degraded=True)
        detail.update(vector_ms=round((time.perf_counter()-t)*1000,2),vector_hits=len(dense))
        rankings=[[i for i,_ in dense if i in by_id],[chunks[i].chunk_id for i,_ in lexical]]
        fused=reciprocal_rank_fusion(rankings,s.fusion_k)
        # Offline vectors are a test fixture, not semantic evidence.
        if s.app_mode=='offline' and not lexical:fused=[]
        candidates=[by_id[i] for i,_ in fused]
        t=time.perf_counter();ranked,rd=await self.reranker.rerank(query,candidates,top_k)
        detail.update(rerank=rd,rerank_ms=round((time.perf_counter()-t)*1000,2),fused=len(fused),
                      total_ms=round((time.perf_counter()-start)*1000,2))
        scores=dict(fused)
        return RetrievalResult(contexts=[c.text for c in ranked],sources=[c.source for c in ranked],
            chunk_ids=[c.chunk_id for c in ranked],scores=[scores[c.chunk_id] for c in ranked],detail=detail,
            evidence_found=bool(ranked))
