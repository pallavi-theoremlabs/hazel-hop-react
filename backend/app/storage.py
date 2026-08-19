"""Document storage, behind one interface with a local and a Volume implementation.

Databricks Apps do **not** FUSE-mount `/Volumes` and do not ship `dbutils`. The
path simply does not exist inside the container, which is why the first deploy
died with a FileNotFoundError chain ending in PermissionError on '/Volumes'. That
was never a grants problem — the READ VOLUME / WRITE VOLUME grants are correct and
are still required, they are just enforced by the Files API rather than by a mount.

So a Volume is reached over the SDK Files API instead, and the local filesystem
path stays for local development. Selection is on the raw UPLOAD_DIR string, the
same conditional shape as db._connect_args.

Verified against databricks-sdk 0.127.0::

    files.upload(file_path: str, contents: BinaryIO, *, overwrite: Optional[bool] = None)
    files.download(file_path: str) -> DownloadResponse   # .contents is Optional[BinaryIO]
    files.delete(file_path: str)

Every method raises FileNotFoundError for a missing object, deliberately: it is an
OSError subclass, so the callers that already catch OSError around file reads keep
working unchanged across both backends.
"""

from __future__ import annotations

import io
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import BACKEND_DIR

logger = logging.getLogger("uvicorn.error")

VOLUME_PREFIX = "/Volumes/"
PROBE_NAME = ".hazel_probe"

# The raw string matters. Path("/Volumes/x") normalises to a backslash form on
# Windows, so the prefix test has to happen before any Path() conversion.
UPLOAD_DIR_RAW = os.getenv("UPLOAD_DIR", "").strip()


class Storage(ABC):
    """Flat key/value document store. `name` is a bare filename, never a path."""

    backend: str

    @abstractmethod
    def write(self, name: str, data: bytes) -> None: ...

    @abstractmethod
    def read(self, name: str) -> bytes: ...

    @abstractmethod
    def delete(self, name: str) -> None: ...

    @abstractmethod
    def probe(self) -> None:
        """Validate at startup that documents can actually be stored."""

    @property
    @abstractmethod
    def location(self) -> str: ...


class LocalStorage(Storage):
    backend = "local"

    def __init__(self, root: Path):
        self.root = root

    @property
    def location(self) -> str:
        return str(self.root)

    def _path(self, name: str) -> Path:
        # Path().name strips any directory component a caller may have passed.
        return self.root / Path(name).name

    def write(self, name: str, data: bytes) -> None:
        self._path(name).write_bytes(data)

    def read(self, name: str) -> bytes:
        return self._path(name).read_bytes()          # FileNotFoundError if absent

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def probe(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self._path(PROBE_NAME)
            probe.write_bytes(b"hazel")
            probe.unlink()
        except OSError as exc:
            raise RuntimeError(
                f"UPLOAD_DIR {self.root} is not writable ({exc}). "
                "Storage backend: local."
            ) from exc


class VolumeStorage(Storage):
    """Unity Catalog Volume via the Files API.

    Note the absence of any mkdir. There is no directory to create over this API,
    and attempting to touch the path as a filesystem is exactly what crashed the
    deploy. The Volume must already exist; probe() confirms it does.
    """

    backend = "volume"

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    @property
    def location(self) -> str:
        return self.base

    def _key(self, name: str) -> str:
        return f"{self.base}/{Path(name).name}"

    def _client(self):
        # Reuse the WorkspaceClient lakebase.py already builds and caches, rather
        # than constructing a second one with its own auth resolution.
        from app.lakebase import workspace

        return workspace()

    def write(self, name: str, data: bytes) -> None:
        self._client().files.upload(self._key(name), io.BytesIO(data), overwrite=True)

    def read(self, name: str) -> bytes:
        key = self._key(name)
        try:
            response = self._client().files.download(key)
        except Exception as exc:
            if _is_not_found(exc):
                raise FileNotFoundError(f"{key} not found in Volume") from exc
            raise
        contents = response.contents
        if contents is None:
            # contents is Optional[BinaryIO]; unguarded this would surface as an
            # AttributeError on None rather than naming the missing object.
            raise FileNotFoundError(f"{key} returned no contents")
        return contents.read()

    def delete(self, name: str) -> None:
        try:
            self._client().files.delete(self._key(name))
        except Exception as exc:
            if _is_not_found(exc):
                return  # delete is idempotent, matching Path.unlink(missing_ok=True)
            raise

    def probe(self) -> None:
        """Round-trip a sentinel, which checks existence and both grants at once."""
        try:
            self.write(PROBE_NAME, b"hazel")
            self.delete(PROBE_NAME)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot write to Volume {self.base} ({type(exc).__name__}: {exc}). "
                "Storage backend: volume (SDK Files API; Apps do not mount /Volumes). "
                "Check that the Volume exists and that the app service principal "
                "holds READ VOLUME and WRITE VOLUME on it, plus USE CATALOG and "
                "USE SCHEMA on its parents."
            ) from exc


def _is_not_found(exc: Exception) -> bool:
    try:
        from databricks.sdk.errors import NotFound

        if isinstance(exc, NotFound):
            return True
    except ImportError:
        pass
    return "not_found" in str(exc).lower() or "does not exist" in str(exc).lower()


def _build() -> Storage:
    if UPLOAD_DIR_RAW.startswith(VOLUME_PREFIX):
        return VolumeStorage(UPLOAD_DIR_RAW)
    root = Path(UPLOAD_DIR_RAW) if UPLOAD_DIR_RAW else BACKEND_DIR / "uploads"
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return LocalStorage(root)


storage: Storage = _build()


def probe_storage() -> None:
    """Startup check. Names the backend and location before doing anything."""
    logger.info(
        "[Hazel] document storage backend=%s location=%s", storage.backend, storage.location
    )
    storage.probe()
    logger.info("[Hazel] document storage is writable")
