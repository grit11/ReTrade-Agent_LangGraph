class AppError(Exception):
    code = 'APPLICATION_ERROR'
    status_code = 400
    def __init__(self, message='请求无法处理'):
        super().__init__(message)
        self.message = message
class NotFound(AppError):
    code = 'NOT_FOUND'
    status_code = 404
class Forbidden(AppError):
    code = 'FORBIDDEN'
    status_code = 403
class Unauthorized(AppError):
    code = 'UNAUTHORIZED'
    status_code = 401
class Conflict(AppError):
    code = 'CONFLICT'
    status_code = 409
class Unavailable(AppError):
    code = 'UPSTREAM_UNAVAILABLE'
    status_code = 503
class ConfigurationError(AppError):
    code = 'CONFIGURATION_ERROR'
    status_code = 503
