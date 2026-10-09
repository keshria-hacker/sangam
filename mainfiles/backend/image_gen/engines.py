"""
image_gen/engines.py — pluggable image generation engines.

All engines are optional and lazy. Missing packages or unreachable servers
degrade to "unavailable" — image-gen never breaks the app.

Engines:
- openai    any OpenAI-compatible /v1/images/generations server
            (OpenAI DALL-E/gpt-image, local OpenAI-compat servers)
- fooocus   EXPERIMENTAL: drives a locally-running Fooocus Gradio UI
            (FOOOCUS_URL, default http://127.0.0.1:7865) via gradio_client.
            Fooocus has no REST API; its generate flow is a chained Gradio
            UI interaction, so this driver is version-sensitive and best
            effort. The openai engine is the reliable path.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class GeneratedImage:
    data: bytes
    mime_type: str  # e.g. "image/png"
    revised_prompt: str = ""  # populated when the server rewrites the prompt


class ImageEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[GeneratedImage]:
        """Generate images. May raise on failure."""
        ...


# --- OpenAI-compatible images API ----------------------------------------------

class OpenAIImagesEngine:
    """POST {base}/v1/images/generations — OpenAI, local compat servers."""

    name = "openai"

    def _config(self) -> tuple[str, str | None, str]:
        from ..config import settings

        return (
            settings.IMAGE_OPENAI_BASE_URL.rstrip("/"),
            settings.IMAGE_OPENAI_API_KEY,
            settings.IMAGE_OPENAI_MODEL,
        )

    def is_available(self) -> bool:
        base, api_key, _model = self._config()
        # api.openai.com needs a key; local servers often don't.
        if "api.openai.com" in base:
            return bool(api_key)
        return bool(base)

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[GeneratedImage]:
        import httpx

        base, api_key, model = self._config()
        if not self.is_available():
            raise RuntimeError("OpenAI image engine not configured (set IMAGE_OPENAI_API_KEY)")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # negative_prompt has no OpenAI equivalent; fold it in is lossy, so we
        # keep the positive prompt clean and let the model handle quality.
        resp = httpx.post(
            f"{base}/v1/images/generations",
            json={"model": model, "prompt": prompt, "size": size, "n": n},
            headers=headers,
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        images: list[GeneratedImage] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
                images.append(GeneratedImage(raw, "image/png", str(item.get("revised_prompt", ""))))
            elif item.get("url"):
                dl = httpx.get(item["url"], timeout=120)
                dl.raise_for_status()
                mime = dl.headers.get("content-type", "image/png").split(";")[0]
                images.append(GeneratedImage(dl.content, mime, str(item.get("revised_prompt", ""))))
        if not images:
            raise RuntimeError("Image server returned no images")
        return images


# --- Fooocus (experimental Gradio driver) ---------------------------------------

class FooocusEngine:
    """EXPERIMENTAL — drive a local Fooocus Gradio UI via gradio_client.

    Fooocus exposes no REST API; generation is a chained Gradio UI flow, so
    this driver introspects the running app's endpoints at call time and
    maps prompt/size onto them. Version-sensitive by nature: any failure
    raises a diagnostic error telling the user what to check.
    Requires: pip install gradio_client, and Fooocus running with --listen.
    """

    name = "fooocus"
    _client: object = None
    _load_error: str = ""

    def _connect(self) -> object:
        if self._client is not None:
            return self._client
        try:
            from gradio_client import Client  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(f"gradio_client not installed: {exc}") from exc
        from ..config import settings

        try:
            self._client = Client(settings.FOOOCUS_URL)
            return self._client
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Cannot reach Fooocus at {settings.FOOOCUS_URL}: {exc}. "
                "Start Fooocus with --listen first."
            ) from exc

    def is_available(self) -> bool:
        if self._load_error:
            return False
        try:
            self._connect()
            return True
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            logger.debug("fooocus unavailable: %s", exc)
            return False

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[GeneratedImage]:
        client = self._connect()
        # Introspect the app: find the txt2img-style predict endpoint.
        # Fooocus versions differ; we try the most likely candidates and
        # fail with a diagnostic listing what exists.
        try:
            api_info = client.view_api(return_format="dict")  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Fooocus API introspection failed: {exc}") from exc
        raise RuntimeError(
            "Fooocus headless generation is experimental and this Fooocus "
            f"version's Gradio endpoints are not mapped yet. Endpoints seen: "
            f"{sorted(api_info.get('named_endpoints', {}).keys())[:10]}. "
            "Generate in the Fooocus UI, or use the openai engine instead."
        )


# --- registry --------------------------------------------------------------------

_ENGINE_PREFERENCE = ("openai", "fooocus")


def _build(name: str) -> ImageEngine | None:
    if name == "openai":
        return OpenAIImagesEngine()
    if name == "fooocus":
        return FooocusEngine()
    return None


def resolve_image_engine(configured: str) -> ImageEngine | None:
    """Pick an image engine. 'auto' tries each in preference order."""
    names = _ENGINE_PREFERENCE if configured == "auto" else (configured,)
    for name in names:
        engine = _build(name)
        if engine is not None and engine.is_available():
            return engine
    return None


def describe_image_engines() -> list[dict]:
    out = []
    for name in ("openai", "fooocus"):
        engine = _build(name)
        available = engine.is_available() if engine else False
        detail = ""
        if name == "fooocus":
            detail = "experimental Gradio driver"
            if isinstance(engine, FooocusEngine) and engine._load_error:
                detail = engine._load_error
        out.append({"name": name, "available": available, "detail": detail})
    return out
