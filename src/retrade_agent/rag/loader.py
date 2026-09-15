"""Rewritten loaders with upload bounds; no arbitrary filesystem path from an LLM."""
import io
import zipfile
from pathlib import Path
from retrade_agent.errors import AppError

ALLOWED_EXTENSIONS={'.txt','.md','.markdown','.pdf','.docx'}

def parse_document(filename:str,raw:bytes)->str:
    ext=Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:raise AppError('仅支持 TXT、Markdown、PDF、DOCX')
    try:
        if ext in {'.txt','.md','.markdown'}:
            text=raw.decode('utf-8-sig')
        elif ext=='.pdf':
            from pypdf import PdfReader
            doc=PdfReader(io.BytesIO(raw))
            if len(doc.pages)>300:raise AppError('PDF 最多 300 页')
            text='\n\n'.join(p.extract_text() or '' for p in doc.pages)
        else:
            from docx import Document
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.infolist())>5000 or sum(i.file_size for i in archive.infolist())>50*1024*1024:
                    raise AppError('DOCX 解压体积超限')
            doc=Document(io.BytesIO(raw))
            blocks=[p.text for p in doc.paragraphs]
            blocks.extend(' | '.join(cell.text for cell in row.cells) for t in doc.tables for row in t.rows)
            text='\n'.join(blocks)
    except AppError:raise
    except Exception as exc:raise AppError('文档解析失败，请检查编码或文件格式') from exc
    if not text.strip():raise AppError('没有可提取的文本；扫描件请先转为文本')
    if len(text)>2_000_000:raise AppError('文档文本过长')
    return text.strip()
