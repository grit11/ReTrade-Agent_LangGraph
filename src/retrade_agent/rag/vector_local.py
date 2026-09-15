import math
class LocalVectors:
    """Vectors persist in document registry; no local neural model is loaded."""
    def __init__(self):self.items=[]
    async def synchronize(self,chunks,generation):self.items=list(chunks)
    async def search(self,vector,k,generation):
        def cosine(v):
            if len(vector)!=len(v):return -1.0
            norm=math.sqrt(sum(x*x for x in vector)*sum(x*x for x in v))
            return sum(a*b for a,b in zip(vector,v))/norm if norm else 0
        rows=[(c.chunk_id,cosine(c.vector)) for c in self.items]
        return sorted(rows,key=lambda x:(-x[1],x[0]))[:k]
    async def close(self):pass
