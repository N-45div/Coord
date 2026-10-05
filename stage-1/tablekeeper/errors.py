"""The single error type every layer raises; the HTTP layer renders it as §5's body."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def malformed(message: str = "request body is not valid JSON of the expected shape") -> ApiError:
    return ApiError(400, "malformed_request", message)


def invalid(message: str) -> ApiError:
    return ApiError(422, "validation_failed", message)


def not_found(message: str = "no such resource") -> ApiError:
    return ApiError(404, "not_found", message)


def unauthenticated(message: str = "a valid bearer token is required") -> ApiError:
    return ApiError(401, "unauthenticated", message)
