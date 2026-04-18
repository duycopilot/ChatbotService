"""
Purpose: Custom exception hierarchy for the application.
All layers (repo, service, route) raise these — HTTP mapping happens at the global handler.
"""


class AppError(Exception):
    """Base exception for all application errors."""
    status_code: int = 500

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    """Resource does not exist."""
    status_code = 404

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message)


class ConflictError(AppError):
    """Resource already exists or state conflict."""
    status_code = 409

    def __init__(self, message: str = "Conflict"):
        super().__init__(message)


class BadRequestError(AppError):
    """Invalid input that passed schema validation but fails business rules."""
    status_code = 400

    def __init__(self, message: str = "Bad request"):
        super().__init__(message)


class UnauthorizedError(AppError):
    """Missing or invalid authentication."""
    status_code = 401

    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message)
