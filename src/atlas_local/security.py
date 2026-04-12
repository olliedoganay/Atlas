from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

try:
    from sqlcipher3 import dbapi2 as sqlcipher_dbapi
except ImportError:  # pragma: no cover - dependency is required in Windows builds
    sqlcipher_dbapi = None

try:
    import keyring
except ImportError:  # pragma: no cover - dependency is required in non-Windows source builds
    keyring = None

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - dependency is required in non-Windows source builds
    AESGCM = None


CRYPTPROTECT_UI_FORBIDDEN = 0x01
_STORAGE_KEY_FORMAT = "atlas-dpapi-storage-key-v1"
_SQLITE_HEADER = b"SQLite format 3\x00"
_NON_WINDOWS_FORMAT = b"atlas-aesgcm-v1\0"
_KEYRING_SERVICE = "Atlas"
_KEYRING_ACCOUNT = "atlas-storage-master-key-v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def protect_bytes(data: bytes, *, entropy: bytes | None = None, description: str = "Atlas") -> bytes:
    if os.name != "nt":
        if not _non_windows_secret_storage_supported():
            return data
        master_key = _get_or_create_non_windows_master_key()
        encryption_key = _derive_non_windows_encryption_key(master_key, entropy=entropy)
        nonce = os.urandom(12)
        encrypted = AESGCM(encryption_key).encrypt(nonce, data, None)
        return _NON_WINDOWS_FORMAT + nonce + encrypted

    input_blob, _input_buffer = _blob_from_bytes(data)
    entropy_blob = _blob_from_bytes(entropy)[0] if entropy else None
    output_blob = _DataBlob()

    result = ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(input_blob),
        ctypes.c_wchar_p(description),
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not result:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)  # type: ignore[attr-defined]


def unprotect_bytes(data: bytes, *, entropy: bytes | None = None) -> bytes:
    if os.name != "nt":
        if not data.startswith(_NON_WINDOWS_FORMAT):
            return data
        if not _non_windows_secret_storage_supported():
            raise RuntimeError("Atlas could not access OS keyring storage on this machine.")
        master_key = _get_or_create_non_windows_master_key()
        encryption_key = _derive_non_windows_encryption_key(master_key, entropy=entropy)
        nonce = data[len(_NON_WINDOWS_FORMAT) : len(_NON_WINDOWS_FORMAT) + 12]
        ciphertext = data[len(_NON_WINDOWS_FORMAT) + 12 :]
        return AESGCM(encryption_key).decrypt(nonce, ciphertext, None)

    input_blob, _input_buffer = _blob_from_bytes(data)
    entropy_blob = _blob_from_bytes(entropy)[0] if entropy else None
    output_blob = _DataBlob()

    result = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not result:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)  # type: ignore[attr-defined]


def sqlcipher_enabled() -> bool:
    return sqlcipher_dbapi is not None


def local_secret_storage_label() -> str:
    if os.name == "nt":
        return "windows-dpapi"
    if _non_windows_secret_storage_supported():
        return "os-keyring"
    return "not-available"


def application_secret_protection_available() -> bool:
    return local_secret_storage_label() != "not-available"


def get_or_create_storage_key(data_dir: Path) -> bytes:
    key_path = data_dir / "storage.key.json"
    if key_path.exists():
        payload = json.loads(key_path.read_text(encoding="utf-8"))
        if payload.get("format") == _STORAGE_KEY_FORMAT:
            wrapped = base64.b64decode(str(payload.get("wrapped_key", "") or "").encode("ascii"))
            return unprotect_bytes(wrapped)

    data_dir.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    payload = {
        "format": _STORAGE_KEY_FORMAT,
        "wrapped_key": base64.b64encode(protect_bytes(key, description="Atlas storage key")).decode("ascii"),
    }
    key_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return key


def _non_windows_secret_storage_supported() -> bool:
    if keyring is None or AESGCM is None:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:
        return False
    return bool(getattr(backend, "priority", 0) > 0)


def _get_or_create_non_windows_master_key() -> bytes:
    if not _non_windows_secret_storage_supported():
        raise RuntimeError("Atlas could not access OS keyring storage on this machine.")
    try:
        stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
        if stored:
            return base64.b64decode(stored.encode("ascii"))
        master_key = os.urandom(32)
        keyring.set_password(
            _KEYRING_SERVICE,
            _KEYRING_ACCOUNT,
            base64.b64encode(master_key).decode("ascii"),
        )
        return master_key
    except Exception as exc:
        raise RuntimeError("Atlas could not access OS keyring storage on this machine.") from exc


def _derive_non_windows_encryption_key(master_key: bytes, *, entropy: bytes | None) -> bytes:
    if not entropy:
        return hashlib.sha256(master_key + b":atlas").digest()
    return hmac.new(master_key, entropy, hashlib.sha256).digest()


def prepare_encrypted_sqlite(path: Path, *, data_dir: Path, reset_legacy: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return
    if not sqlcipher_enabled():
        return
    if reset_legacy and _looks_like_plaintext_sqlite(path):
        _unlink_with_retry(path)


def prepare_encrypted_qdrant_storage(path: Path, *, data_dir: Path, reset_legacy: bool = True) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not reset_legacy:
        return
    if not sqlcipher_enabled():
        return
    for storage_path in path.rglob("storage.sqlite"):
        if _looks_like_plaintext_sqlite(storage_path):
            _rmtree_with_retry(path)
            path.mkdir(parents=True, exist_ok=True)
            return


def open_application_sqlite(
    database: str | Path,
    *,
    data_dir: Path,
    check_same_thread: bool = False,
) -> Any:
    if not sqlcipher_enabled():
        return sqlite3.connect(str(database), check_same_thread=check_same_thread)

    target = Path(str(database)) if str(database) != ":memory:" else None
    if target is not None:
        prepare_encrypted_sqlite(target, data_dir=data_dir)
    connection = sqlcipher_dbapi.connect(str(database), check_same_thread=check_same_thread)
    _apply_sqlcipher_key(connection, get_or_create_storage_key(data_dir))
    return connection


def build_encrypted_sqlite_module(*, data_dir: Path) -> Any:
    if not sqlcipher_enabled():
        return sqlite3

    class _SqlcipherModuleProxy:
        def __getattr__(self, name: str) -> Any:
            return getattr(sqlcipher_dbapi, name)

        def connect(self, database: str | Path, *args: Any, **kwargs: Any) -> Any:
            target = None if str(database) == ":memory:" else Path(str(database))
            if target is not None:
                prepare_encrypted_sqlite(target, data_dir=data_dir)
            connection = sqlcipher_dbapi.connect(str(database), *args, **kwargs)
            _apply_sqlcipher_key(connection, get_or_create_storage_key(data_dir))
            return connection

    return _SqlcipherModuleProxy()


def _apply_sqlcipher_key(connection: Any, key: bytes) -> None:
    if sqlcipher_dbapi is None:
        return
    connection.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
    connection.execute("SELECT count(*) FROM sqlite_master")


def _looks_like_plaintext_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


def _unlink_with_retry(path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(6):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _rmtree_with_retry(path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(6):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _blob_from_bytes(data: bytes | None) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    raw = data or b""
    buffer = ctypes.create_string_buffer(raw, len(raw))
    blob = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer
