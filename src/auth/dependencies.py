"""Auth dependencies: session guard used by protected routes."""

from fastapi import Request


class LoginRequired(Exception):
    """Raised when a protected route is accessed without an authenticated session."""

    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def require_session(request: Request):
    """FastAPI dependency: ensure the user is logged in, else raise LoginRequired."""
    if "user_id" not in request.session:
        raise LoginRequired(next_url=str(request.url))
    return request.session
