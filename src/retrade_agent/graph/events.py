"""Safe operational events only. Never emit raw model prompts, secrets or reasoning."""


def emit(event_type, **fields):
    """向 LangGraph 运行上下文发送自定义进度事件。"""
    from langgraph.config import get_stream_writer

    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"type": event_type, **fields})
