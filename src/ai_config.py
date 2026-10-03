"""AI provider settings and credentials for the desktop app."""

from urllib.parse import urlsplit
from io import BytesIO
import base64

import keyring
from openai import OpenAI
from PIL import Image


SERVICE = "InstagramSavedArchiver"
PROVIDER_URLS = {
    "9router": "http://127.0.0.1:20128/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
DEFAULT_MODEL = "gemini/gemini-3.5-flash-lite"


def base_url(provider, custom_url=None):
    if provider in PROVIDER_URLS:
        return PROVIDER_URLS[provider]
    if provider != "custom":
        raise ValueError("Unknown AI provider")
    url = (custom_url or keyring.get_password(SERVICE, "ai_custom_url") or "").strip().rstrip("/")
    parts = urlsplit(url)
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or parts.scheme not in {"https", "http"}
            or (parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1"})):
        raise ValueError("Custom API URL must use HTTPS or local loopback HTTP")
    return url


def provider_key(provider):
    return keyring.get_password(SERVICE, provider)


def current():
    provider = keyring.get_password(SERVICE, "ai_provider") or "9router"
    model = keyring.get_password(SERVICE, f"ai_model:{provider}") or (DEFAULT_MODEL if provider == "9router" else "")
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url(provider),
        "key_configured": bool(provider_key(provider)),
        "configured": bool(provider_key(provider) and model),
    }


def save(provider, model, api_key=None, custom_url=None):
    url = base_url(provider, custom_url)
    model = model.strip()
    if not model or len(model) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in model):
        raise ValueError("Invalid model name")
    if provider == "custom" and custom_url and url != keyring.get_password(SERVICE, "ai_custom_url") and not api_key:
        raise ValueError("Enter the API key when changing the custom URL")
    if api_key:
        if not 10 <= len(api_key) <= 512 or any(ord(char) < 33 or ord(char) > 126 for char in api_key):
            raise ValueError("Invalid API key")
        keyring.set_password(SERVICE, provider, api_key)
    if provider == "custom":
        keyring.set_password(SERVICE, "ai_custom_url", url)
    keyring.set_password(SERVICE, f"ai_model:{provider}", model)
    keyring.set_password(SERVICE, "ai_provider", provider)
    return current()


def client(provider, custom_url=None, api_key=None):
    key = api_key or provider_key(provider)
    if not key:
        raise ValueError("Add an API key for this provider in Settings")
    if provider == "custom" and custom_url and custom_url.rstrip("/") != (keyring.get_password(SERVICE, "ai_custom_url") or "") and not api_key:
        raise ValueError("Enter the API key for this custom URL")
    return OpenAI(api_key=key, base_url=base_url(provider, custom_url), timeout=60, max_retries=0)


def list_models(provider, custom_url=None, api_key=None):
    api = client(provider, custom_url, api_key)
    try:
        models = []
        for item in api.models.list():
            raw = item.model_dump(exclude_none=True)
            capabilities = raw.get("capabilities") or {}
            architecture = raw.get("architecture") or {}
            vision = capabilities.get("vision")
            if vision is None and architecture.get("input_modalities"):
                vision = "image" in architecture["input_modalities"]
            models.append({"id": item.id, "vision": vision})
        return sorted(models, key=lambda entry: entry["id"].lower())[:1000]
    finally:
        api.close()


def test_vision(provider, model, custom_url=None, api_key=None):
    """Send a synthetic 1-pixel image; never send archived media in a connection test."""
    if not model or len(model) > 200:
        raise ValueError('Select a vision model first')
    api = client(provider, custom_url, api_key)
    try:
        image = BytesIO()
        Image.new('RGB', (1, 1), 'white').save(image, format='PNG')
        reply = api.chat.completions.create(model=model, max_tokens=16, messages=[{
            'role': 'user', 'content': [
                {'type': 'text', 'text': 'Reply OK if you can read this image.'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode('ascii')}}
            ]
        }])
        return {'ok': bool(reply.choices and reply.choices[0].message.content)}
    finally:
        api.close()
