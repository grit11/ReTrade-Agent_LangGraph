"""仅发送安全的运行事件，不输出原始模型提示、密钥或推理内容。"""


def emit(event_type, **fields):
    """向 LangGraph 运行上下文发送自定义进度事件。"""
    from langgraph.config import get_stream_writer

    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"type": event_type, **fields})
