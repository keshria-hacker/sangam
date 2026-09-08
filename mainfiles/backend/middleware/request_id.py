"""
Request ID Middleware - Generates/extracts and propagates request IDs for distributed tracing.

Runs as the FIRST middleware so request_id is available to all downstream middleware and routes.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Extract or generate a unique request ID and propagate it through the request/response cycle.

    - Reads X-Request-ID header from incoming request (for trace continuation)
    - Generates new UUID v4 if header not present
    - Stores request_id in request.state.request_id for downstream access
    - Adds X-Request-ID header to all responses
    """

    HEADER_NAME = "X-Request-ID"
    HEADER_NAME_LOWER = "x-request-id"
    STATE_KEY = "request_id"

    async def dispatch(self, request: Request, call_next):
        # Extract or generate request ID (headers are normalized to lowercase by Starlette)
        request_id = request.headers.get(self.HEADER_NAME_LOWER)
        if not request_id:
            # Generate a short UUID (12 chars from 32-char hex)
            request_id = uuid.uuid4().hex[:12]

        # Store in request state for downstream middleware/routes
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Propagate request ID in response header
        response.headers[self.HEADER_NAME] = request_id
        return response


def get_request_id(request: Request) -> str:
    """Get the request ID from request state (set by RequestIDMiddleware)."""
    return getattr(request.state, "request_id", "unknown")