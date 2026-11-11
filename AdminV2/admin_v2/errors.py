"""Typed API errors. Messages are plain words, never stack traces, SQL, or secrets."""


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def bad(message="That input is not valid. Check the field and try again."):
    return ApiError("invalid_params", message, 400)


def unauth(message="Log in to use the admin panel."):
    return ApiError("unauthenticated", message, 401)


def forbidden(message="You do not have permission for that action."):
    return ApiError("forbidden", message, 403)


def not_found(message="That item was not found."):
    return ApiError("not_found", message, 404)


def conflict(message="That action conflicts with the current state."):
    return ApiError("conflict", message, 409)


def rate_limited(message="Too many tries. Wait a moment and try again."):
    return ApiError("rate_limited", message, 429)
