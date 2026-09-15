"""应用异常模块，定义业务错误类型及其统一错误码。"""


class AppError(Exception):
    """业务异常基类，携带对外展示消息和统一错误码。"""

    code = "APPLICATION_ERROR"
    status_code = 400

    def __init__(self, message="请求无法处理"):
        """初始化实例依赖和内部状态。"""
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    """资源不存在错误。"""

    code = "NOT_FOUND"
    status_code = 404


class Forbidden(AppError):
    """权限不足错误。"""

    code = "FORBIDDEN"
    status_code = 403


class Unauthorized(AppError):
    """未认证或令牌无效错误。"""

    code = "UNAUTHORIZED"
    status_code = 401


class Conflict(AppError):
    """并发冲突或幂等参数冲突错误。"""

    code = "CONFLICT"
    status_code = 409


class Unavailable(AppError):
    """外部依赖或服务暂不可用错误。"""

    code = "UPSTREAM_UNAVAILABLE"
    status_code = 503


class ConfigurationError(AppError):
    """配置缺失或配置不合法错误。"""

    code = "CONFIGURATION_ERROR"
    status_code = 503
