import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Literal

from fastapi import Request
from pydantic import AwareDatetime, Field

from msa.contracts.common import Contract, Identifier

from .problem import Problem


class Principal(Contract):
    actor: Identifier
    role: Literal["analyst", "risk_manager", "admin", "demo"]
    scopes: frozenset[str] = Field(min_length=1)
    expires_at: AwareDatetime
    key_id: str = ""


class KeyStore:
    def __init__(self, keys=None):
        keys = json.loads(os.getenv("MSA_API_KEYS", "{}")) if keys is None else keys
        self.keys = {
            hashlib.sha256(key.encode()).hexdigest(): Principal.model_validate(value)
            for key, value in keys.items()
        }

    def authenticate(self, key):
        digest = hashlib.sha256(key.encode()).hexdigest()
        principal = next((p for k, p in self.keys.items() if hmac.compare_digest(k, digest)), None)
        if principal is None or principal.expires_at <= datetime.now(UTC):
            raise Problem(401, "Missing, invalid or expired API key")
        return principal.model_copy(update={"key_id": digest})


def api_key_auth(request: Request) -> Principal:
    key = request.headers.get("X-API-Key")
    principal = request.app.state.keys.authenticate(key or "")
    request.state.principal = principal
    return principal


def require_scope(principal, scope):
    namespace = scope.split(":")[0]
    if principal.role == "demo" and namespace != "demo":
        raise Problem(403, "Demo keys cannot access production resources")
    if not ({scope, namespace + ":*", "admin:*"} & principal.scopes):
        raise Problem(403, f"Missing scope: {scope}")


def require_role(principal, *roles):
    if principal.role not in {*roles, "admin"}:
        raise Problem(403, "Role does not permit this operation")
