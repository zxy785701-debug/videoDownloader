class AnalysisError(ValueError):
    """Only safe application messages; never expose upstream bodies or credentials."""

    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class JobStopped(Exception):
    pass


class OutputLimitError(AnalysisError):
    """A complete transport response stopped at the model's output budget."""

    def __init__(self):
        super().__init__("AI_OUTPUT_INVALID", "模型达到本次输出长度上限，未保存为完整结果。")
