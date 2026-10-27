class BusinessException(Exception):
    """业务异常，由全局异常处理器统一转换为标准错误响应。"""

    def __init__(self, code: int = 400, message: str = "业务处理失败") -> None:
        self.code = code
        self.message = message
        super().__init__(message)
