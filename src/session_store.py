"""Keep Instagram session data encrypted on disk for the current Windows user."""

import json
import os
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken


SERVICE = "InstagramSavedArchiver"


def _cipher():
    key = keyring.get_password(SERVICE, "instagram_session_key")
    if not key:
        key = Fernet.generate_key().decode("ascii")
        keyring.set_password(SERVICE, "instagram_session_key", key)
    return Fernet(key.encode("ascii"))


def _settings(raw):
    settings = json.loads(raw)
    if not isinstance(settings, dict):
        raise ValueError("Invalid Instagram session")
    return settings


def save_session(settings, path):
    payload = json.dumps(settings).encode("utf-8")
    encrypted = _cipher().encrypt(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(encrypted)
    os.replace(temporary, target)


def import_session(contents, path):
    save_session(parse_session(contents), path)


def parse_session(contents):
    if len(contents) > 2_000_000:
        raise ValueError("Session file is too large")
    try:
        if contents.lstrip().startswith(b"{"):
            settings = _settings(contents)
        else:
            settings = _settings(_cipher().decrypt(contents))
    except (InvalidToken, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid Instagram session") from exc
    return settings


def account_id(settings):
    auth = settings.get("authorization_data") or {}
    return auth.get("ds_user_id") or settings.get("ds_user_id")


def load_session(path):
    try:
        return _settings(_cipher().decrypt(Path(path).read_bytes()))
    except (InvalidToken, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ValueError("Instagram session could not be decrypted") from exc
