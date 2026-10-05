class AnalysisError(ValueError):
    """Only safe application messages; never expose upstream bodies or credentials."""

    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class JobStopped(Exception):
    pass
