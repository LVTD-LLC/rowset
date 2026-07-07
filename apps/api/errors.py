class DatasetServiceError(Exception):
    def __init__(self, status_code: int, message: str, *, details: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(message)
