from typing import Annotated

from fastapi import Depends, Request

from .auth import Principal, api_key_auth, require_scope

Authenticated = Annotated[Principal, Depends(api_key_auth)]


def access(request: Request, principal: Principal, action: str = "read") -> str:
    """The namespace of a request is its path: /v1/demo/... is demo, the rest production."""
    scope = "demo" if request.url.path.startswith("/v1/demo/") else "production"
    require_scope(principal, scope + ":" + action)
    return scope
