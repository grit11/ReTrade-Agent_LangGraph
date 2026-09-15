"""BM25 design migrated from ReTrade_V2; rewritten, dependency-injectable tokenizer.
Uses positive IDF smoothing. In a full install segmentation is jieba; the built-in
bigram fallback only keeps minimal unit tests/imports usable without that dependency.
"""
import math
import re
from collections import Counter
from collections.abc import Callable

def tokenize(text:str)->list[str]:
    text=text.lower()
    try:
        import jieba
        return [t.strip() for t in jieba.lcut(text) if t.strip() and re.search(r'\w',t)]
    except ImportError:
        words=re.findall(r'[a-z0-9]+',text)
        for part in re.findall(r'[\u4e00-\u9fff]+',text):
            words.extend(part[i:i+2] for i in range(max(1,len(part)-1)))
        return words

class BM25:
    def __init__(self,texts:list[str],tokenizer:Callable=tokenize,k1=1.5,b=0.75):
        self.tokenizer=tokenizer;self.k1=k1;self.b=b
        self.docs=[Counter(tokenizer(t)) for t in texts]
        self.lengths=[sum(c.values()) for c in self.docs]
        self.avgdl=sum(self.lengths)/len(texts) if texts else 1
        self.df=Counter(t for c in self.docs for t in c)
    def search(self,query:str,k:int):
        scores=[];n=len(self.docs)
        query_terms=set(self.tokenizer(query))
        for i,doc in enumerate(self.docs):
            score=0.0
            for token in query_terms:
                tf=doc.get(token,0)
                if not tf:continue
                df=self.df[token];idf=math.log(1+(n-df+0.5)/(df+0.5))
                score+=idf*tf*(self.k1+1)/(tf+self.k1*(1-self.b+self.b*self.lengths[i]/max(self.avgdl,1)))
            if score>0:scores.append((i,score))
        return sorted(scores,key=lambda pair:(-pair[1],pair[0]))[:k]
