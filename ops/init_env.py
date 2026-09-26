"""Generate local credentials once; never overwrite an existing environment."""

import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Keys generated below become API principals; the API reads them from MSA_API_KEYS.
PRINCIPALS = (
    ("MSA_UI_ANALYST_API_KEY", "ui-analyst", "analyst", ["production:*", "demo:*"]),
    ("MSA_UI_RISK_MANAGER_API_KEY", "ui-risk-manager", "risk_manager", ["production:*", "demo:*"]),
)


#: The platform schema lives in its own database; the pre-platform database "msa" is kept.
DATABASE = "msa_platform"


def init_env(root: Path) -> bool:
    path = root / ".env"
    if path.exists():
        return False
    lines = []
    values = {}
    for line in (root / ".env.example").read_text().splitlines():
        if line.endswith("CHANGE_ME") and "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value.removesuffix("CHANGE_ME") + secrets.token_hex(32)
            line = f"{name}={values[name]}"
        lines.append(line)
    lines.append(
        f"MSA_DATABASE_URL=postgresql://msa:{values['POSTGRES_PASSWORD']}@127.0.0.1:5433/{DATABASE}"
    )
    expires_at = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    keys = {
        values[variable]: {"actor": actor, "role": role, "scopes": scopes, "expires_at": expires_at}
        for variable, actor, role, scopes in PRINCIPALS
    }
    lines.append(f"MSA_API_KEYS='{json.dumps(keys, separators=(',', ':'))}'")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write("\n".join(lines) + "\n")
    return True


if __name__ == "__main__":
    print(
        "Created .env" if init_env(Path(__file__).resolve().parents[1]) else "Using existing .env"
    )
