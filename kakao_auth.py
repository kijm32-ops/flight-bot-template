"""Encrypted, repository-persisted Kakao refresh-token storage."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


AUTH_FILE = Path(__file__).resolve().parent / "data" / "kakao_auth.json"
AUTH_VERSION = 1


class KakaoAuthError(RuntimeError):
    """Raised when a persisted Kakao token cannot be safely used."""


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _fernet(encryption_key: str) -> Fernet:
    if not encryption_key:
        raise KakaoAuthError("KAKAO_TOKEN_ENCRYPTION_KEY is required.")
    try:
        return Fernet(encryption_key.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise KakaoAuthError("KAKAO_TOKEN_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def load_refresh_token(encryption_key: str, auth_file: Path = AUTH_FILE) -> Optional[str]:
    """Decrypt and return the stored refresh token, or None before OAuth setup."""
    if not auth_file.exists():
        return None
    try:
        payload = json.loads(auth_file.read_text(encoding="utf-8"))
        if payload.get("version") != AUTH_VERSION or not isinstance(payload.get("token"), str):
            raise KakaoAuthError("Kakao auth file has an unsupported format.")
        return _fernet(encryption_key).decrypt(payload["token"].encode("ascii")).decode("utf-8")
    except (OSError, json.JSONDecodeError, InvalidToken, UnicodeDecodeError) as exc:
        raise KakaoAuthError("Kakao refresh token could not be read or decrypted.") from exc


def store_refresh_token(refresh_token: str, encryption_key: str, auth_file: Path = AUTH_FILE) -> None:
    """Encrypt and atomically replace the stored refresh token without logging it."""
    if not refresh_token:
        raise KakaoAuthError("Refusing to store an empty refresh token.")
    encrypted = _fernet(encryption_key).encrypt(refresh_token.encode("utf-8")).decode("ascii")
    payload = {"version": AUTH_VERSION, "token": encrypted}
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=auth_file.parent, delete=False) as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
            temporary_path = Path(handle.name)
        os.replace(temporary_path, auth_file)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except UnboundLocalError:
            pass
        raise KakaoAuthError("Kakao refresh token could not be persisted.") from exc
