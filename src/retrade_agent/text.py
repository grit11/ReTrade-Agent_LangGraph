"""Small deterministic input guard, not model-based authorization."""
GREETINGS={'你好','您好','hi','hello','谢谢','谢谢你','再见','早上好','晚上好'}
def human_requested(text):
    return any(x in text for x in ('转人工','找人工','人工客服','真人客服','我要人工'))
