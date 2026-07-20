class DatasetServiceError(Exception):
    def __init__(self, status_code: int, message: str, *, public_access_state: str = ""):
        self.status_code = status_code
        self.message = message
        self.public_access_state = public_access_state
        super().__init__(message)
