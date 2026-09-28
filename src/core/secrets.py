"""Encrypt secrets with Windows DPAPI so only this Windows user can read them.

StreamDock keeps global settings as plain JSON on disk; the LibreLinkUp
password is stored there only in this encrypted form.
"""

import base64
import ctypes
import ctypes.wintypes as wt


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _from_blob(blob: _Blob) -> bytes:
    data = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return data


def protect(text: str) -> str:
    blob_in, _keep = _to_blob(text.encode("utf-8"))
    blob_out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptProtectData failed")
    return base64.b64encode(_from_blob(blob_out)).decode("ascii")


def unprotect(token: str) -> str:
    blob_in, _keep = _to_blob(base64.b64decode(token))
    blob_out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData failed")
    return _from_blob(blob_out).decode("utf-8")
