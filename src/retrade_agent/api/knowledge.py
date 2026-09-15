from fastapi import APIRouter,Request,UploadFile,File,Depends
from retrade_agent.api.auth import require_staff
from retrade_agent.api.schemas import KnowledgeQuery
from retrade_agent.errors import AppError
router=APIRouter(prefix='/api/v1/knowledge')
@router.get('')
async def documents(request:Request,actor=Depends(require_staff)):
    c=request.app.state.container
    return {'documents':await c.knowledge.list_documents(),'generation':c.knowledge.retriever.generation,
            'last_error':c.knowledge.last_error}
@router.post('/ingest')
async def ingest(request:Request,file:UploadFile=File(...),actor=Depends(require_staff)):
    c=request.app.state.container;limit=c.settings.max_upload_mb*1024*1024
    data=bytearray()
    try:
        while chunk:=await file.read(65536):
            data.extend(chunk)
            if len(data)>limit:raise AppError('文件过大')
        return await c.knowledge.ingest(file.filename or '',bytes(data))
    finally:await file.close()
@router.post('/rebuild')
async def rebuild(request:Request,actor=Depends(require_staff)):
    c=request.app.state.container
    async with c.knowledge.lock:await c.knowledge.rebuild()
    return {'ok':True,'generation':c.knowledge.retriever.generation}
@router.post('/search')
async def search(body:KnowledgeQuery,request:Request,actor=Depends(require_staff)):
    return (await request.app.state.container.knowledge.search(body.query)).model_dump()
@router.delete('/{document_id}')
async def remove(document_id:str,request:Request,actor=Depends(require_staff)):
    await request.app.state.container.knowledge.remove(document_id)
    return {'ok':True}
