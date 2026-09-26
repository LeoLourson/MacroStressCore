"""Atomic immutable local object storage. SHA-256 is the document identifier."""

import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path

from msa.config import settings


class IntegrityError(OSError):
    pass


class OriginalStore:
    def __init__(self, root=None):
        self.root = Path(root if root is not None else settings().storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Expected lowercase SHA-256")
        path = self.root / digest[:2] / digest[2:4] / digest
        # Only fixed hex components are allowed. Reject redirected directories;
        # resolving the leaf races with atomic hard-link publication on Windows.
        for component in (path.parent.parent, path.parent, path):
            if component.is_symlink() or component.is_junction():
                raise ValueError("Object path cannot contain a symlink or junction")
        return path

    def put(self, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise TypeError("Original must be bytes")
        digest = sha256(data).hexdigest()
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.get(digest)
            return digest
        fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Hard-link publication is atomic and cannot overwrite an existing object.
                os.link(temporary, path)
            except FileExistsError:
                self.get(digest)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return digest

    def get(self, digest: str) -> bytes:
        data = self._path(digest).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise IntegrityError(f"Object failed SHA-256 verification: {digest}")
        return data

    @staticmethod
    def doc_id_for(digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Expected lowercase SHA-256")
        return digest


def put(data: bytes) -> str:
    return OriginalStore().put(data)


def get(digest: str) -> bytes:
    return OriginalStore().get(digest)


def doc_id_for(digest: str) -> str:
    return OriginalStore.doc_id_for(digest)
