"""Heading-aware chunking, deterministic IDs and source links."""
import hashlib
import re
from retrade_agent.rag.schemas import Chunk

def split_text(title:str,text:str,size=500,overlap=80)->list[Chunk]:
    if size<1 or overlap<0 or overlap>=size:raise ValueError('invalid chunk size/overlap')
    doc_id=hashlib.sha256(title.encode()).hexdigest()[:24]
    revision=hashlib.sha256(text.encode()).hexdigest()[:16]
    sections=[];current=[];heading=''
    for line in text.splitlines():
        if re.match(r'^#{1,6}\s+',line):
            if current:sections.append((heading,'\n'.join(current).strip()))
            heading=line;current=[]
        else:current.append(line)
    if current:sections.append((heading,'\n'.join(current).strip()))
    if not sections:sections=[('',text)]
    chunks=[]
    for heading,body in sections:
        if not body:continue
        full=(heading+'\n'+body).strip();start=0
        while start<len(full):
            end=min(start+size,len(full))
            if end<len(full):
                cuts=[full.rfind(s,start+size//2,end) for s in ('\n','。','；','！','？',' ') ]
                cut=max(cuts)
                if cut>start:end=cut+1
            part=full[start:end].strip()
            if part:
                i=len(chunks)
                chunks.append(Chunk(chunk_id=f'{doc_id}:{revision}:{i}',document_id=doc_id,
                                    source=f'{title}#{i}',text=part))
            if end==len(full):break
            start=max(start+1,end-overlap)
    return chunks
