"""Safe operational events only. Never emit raw model prompts, secrets or reasoning."""
def emit(event_type,**fields):
    from langgraph.config import get_stream_writer
    try:writer=get_stream_writer()
    except RuntimeError:return
    writer({'type':event_type,**fields})
