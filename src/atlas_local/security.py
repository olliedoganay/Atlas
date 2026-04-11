from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def protect_bytes(data: bytes, *, entropy: bytes | None = None, description: str = "Atlas") -> bytes:
    if os.name != "nt":
        return data

    input_blob, input_buffer = _blob_from_bytes(data)
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
        return data

    input_blob, input_buffer = _blob_from_bytes(data)
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


def _blob_from_bytes(data: bytes | None) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    raw = data or b""
    buffer = ctypes.create_string_buffer(raw, len(raw))
    blob = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer
