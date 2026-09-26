from hashlib import sha256
from pathlib import Path

VERSION = "0.1.0"


def code_sha256(root: Path | None = None) -> str:
    """Hash sorted package-relative names and bytes, independent of checkout path/mtime."""
    root = root or Path(__file__).resolve().parent
    digest = sha256()
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()
