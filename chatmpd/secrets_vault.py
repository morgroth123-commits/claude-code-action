"""Windows-protected secret storage for optional ChatMPD connectors."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from datetime import UTC, datetime
from typing import Protocol

from .platform_db import PlatformDatabase


class Cipher(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class DPAPICipher:
    """Protect bytes for the current Windows user using DPAPI."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("DPAPI secret protection is only available on Windows.")
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    @staticmethod
    def _blob(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data)
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        return _DATA_BLOB(len(data), pointer), buffer

    def protect(self, data: bytes) -> bytes:
        source, keepalive = self._blob(bytes(data))
        output = _DATA_BLOB()
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        )
        _ = keepalive
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def unprotect(self, data: bytes) -> bytes:
        source, keepalive = self._blob(bytes(data))
        output = _DATA_BLOB()
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        )
        _ = keepalive
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)


class SecretsVault:
    def __init__(
        self,
        database: PlatformDatabase | None = None,
        *,
        cipher: Cipher | None = None,
    ) -> None:
        self.database = database or PlatformDatabase()
        self.cipher = cipher or DPAPICipher()

    @staticmethod
    def _name(value: str) -> str:
        name = "-".join(str(value).strip().casefold().split())
        if not name or len(name) > 120:
            raise ValueError("Secret name must be 1-120 characters.")
        return name

    def set(self, name: str, value: str) -> str:
        clean = self._name(name)
        raw = str(value).encode("utf-8")
        if not raw:
            raise ValueError("Secret value cannot be blank.")
        protected = self.cipher.protect(raw)
        payload = json.dumps({"ciphertext": base64.b64encode(protected).decode("ascii")})
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("secret", clean, payload, now),
            )
            connection.commit()
        return clean

    def get(self, name: str) -> str:
        clean = self._name(name)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("secret", clean),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown secret: {clean}")
        data = json.loads(str(row["payload"]))
        ciphertext = base64.b64decode(str(data["ciphertext"]), validate=True)
        return self.cipher.unprotect(ciphertext).decode("utf-8")

    def names(self) -> tuple[str, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT record_id FROM platform_records WHERE namespace=? ORDER BY record_id",
                ("secret",),
            ).fetchall()
        return tuple(str(row["record_id"]) for row in rows)

    def delete(self, name: str) -> bool:
        clean = self._name(name)
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM platform_records WHERE namespace=? AND record_id=?",
                ("secret", clean),
            )
            connection.commit()
            return cursor.rowcount > 0
