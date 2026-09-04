"""Pairing and revocable mobile-device credentials for ChatMPD."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4


def _default_mobile_state_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    return base / "ChatMPD" / "mobile"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PairingTicket:
    code: str
    expires_at: float

@dataclass(frozen=True)
class PairedDevice:
    device_id: str
    name: str
    created_at: float


@dataclass(frozen=True)
class DeviceCredential:
    device_id: str
    device_name: str
    token: str


@dataclass
class _PairingState:
    digest: str
    expires_at: float
    attempts_left: int


class DeviceCredentialStore:
    """Own short-lived pairing state and persistent token digests."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
        pairing_ttl_seconds: float = 600.0,
        max_pair_attempts: int = 5,
    ) -> None:
        if pairing_ttl_seconds <= 0:
            raise ValueError("pairing_ttl_seconds must be positive")
        if max_pair_attempts < 1:
            raise ValueError("max_pair_attempts must be at least 1")
        self.root = Path(root or _default_mobile_state_dir())
        self.path = self.root / "devices.json"
        self._clock = clock
        self._pairing_ttl = float(pairing_ttl_seconds)
        self._max_pair_attempts = int(max_pair_attempts)
        self._pairing: _PairingState | None = None
        self._devices = self._load_devices()

    def issue_pairing_code(self) -> PairingTicket:
        code = f"{secrets.randbelow(100_000_000):08d}"
        expires_at = self._clock() + self._pairing_ttl
        self._pairing = _PairingState(
            digest=_digest(code),
            expires_at=expires_at,
            attempts_left=self._max_pair_attempts,
        )
        return PairingTicket(code=code, expires_at=expires_at)

    def begin_pairing(self, *, ttl_seconds: float | None = None) -> str:
        ttl = self._pairing_ttl if ttl_seconds is None else float(ttl_seconds)
        if ttl <= 0:
            raise ValueError("Pairing TTL must be positive.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._pairing = _PairingState(
            digest=_digest(code),
            expires_at=self._clock() + ttl,
            attempts_left=self._max_pair_attempts,
        )
        return code

    def pair(self, code: str, device_name: str) -> DeviceCredential:
        token = self.exchange_pairing_code(code, device_name)
        digest = _digest(token)
        record = next(
            device for device in reversed(self._devices)
            if hmac.compare_digest(digest, str(device["token_digest"]))
        )
        return DeviceCredential(
            device_id=str(record["device_id"]),
            device_name=str(record["name"]),
            token=token,
        )

    def verify(self, token: str) -> bool:
        return self.validate_token(token)

    def exchange_pairing_code(self, code: str, device_name: str) -> str:
        name = str(device_name).strip()
        if not name or len(name) > 80:
            raise ValueError("Device name must contain 1 to 80 characters.")
        pairing = self._pairing
        if pairing is None:
            raise ValueError("No active pairing session.")
        if self._clock() > pairing.expires_at:
            self._pairing = None
            raise ValueError("The pairing code expired.")
        supplied = _digest(str(code).strip())
        if not hmac.compare_digest(supplied, pairing.digest):
            pairing.attempts_left -= 1
            if pairing.attempts_left <= 0:
                self._pairing = None
            raise ValueError("Invalid pairing code.")

        self._pairing = None
        token = secrets.token_urlsafe(32)
        record = {
            "device_id": uuid4().hex,
            "name": name,
            "token_digest": _digest(token),
            "created_at": self._clock(),
        }
        self._devices.append(record)
        self._save_devices()
        return token

    def validate_token(self, token: str) -> bool:
        candidate = str(token).strip()
        if not candidate:
            return False
        candidate_digest = _digest(candidate)
        return any(
            hmac.compare_digest(candidate_digest, str(device["token_digest"]))
            for device in self._devices
        )

    def list_devices(self) -> tuple[PairedDevice, ...]:
        return tuple(
            PairedDevice(
                device_id=str(device["device_id"]),
                name=str(device["name"]),
                created_at=float(device["created_at"]),
            )
            for device in sorted(
                self._devices, key=lambda item: float(item["created_at"])
            )
        )

    def revoke(self, device_id: str) -> bool:
        target = str(device_id).strip()
        remaining = [
            device for device in self._devices if str(device["device_id"]) != target
        ]
        if len(remaining) == len(self._devices):
            return False
        self._devices = remaining
        self._save_devices()
        return True

    def _load_devices(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read mobile device credentials: {exc}") from exc
        devices = payload.get("devices") if isinstance(payload, dict) else None
        if not isinstance(devices, list):
            raise RuntimeError("Mobile credential file has an invalid schema.")
        cleaned: list[dict[str, object]] = []
        for device in devices:
            if not isinstance(device, dict):
                continue
            required = {"device_id", "name", "token_digest", "created_at"}
            if not required.issubset(device):
                continue
            cleaned.append(dict(device))
        return cleaned

    def _save_devices(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "devices": self._devices}
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.root, delete=False
        ) as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            temporary = Path(stream.name)
        try:
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
