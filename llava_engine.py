from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from nlp_namer import sanitize_keywords
from settings import AppSettings


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlavaResult:
    success: bool
    keywords: list[str]
    confidence: float
    raw_response: str
    error: str | None = None


class LlavaEngine:
    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self.timeout_seconds = timeout_seconds

    def describe_image(
        self,
        image_path: Path,
        settings: AppSettings,
    ) -> LlavaResult:
        try:
            encoded_image = base64.b64encode(
                image_path.read_bytes()
            ).decode("ascii")
        except OSError as exc:
            LOGGER.exception("Could not read image for LLaVA: %s", image_path)
            return LlavaResult(False, [], 0.0, "", str(exc))

        payload: dict[str, Any] = {
            "model": settings.ollama_model,
            "prompt": (
                "Describe what is shown in this screenshot in 8 words or "
                "fewer, focusing on the application, command, or topic "
                "visible. Respond with only lowercase keywords separated by "
                "underscores, no punctuation."
            ),
            "images": [encoded_image],
            "stream": False,
        }
        endpoint = settings.ollama_url.rstrip("/") + "/api/generate"

        try:
            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            LOGGER.warning("Ollama/LLaVA unavailable: %s", exc)
            return LlavaResult(False, [], 0.0, "", str(exc))
        except ValueError as exc:
            LOGGER.warning("Ollama returned invalid JSON: %s", exc)
            return LlavaResult(False, [], 0.0, "", str(exc))

        raw_response = str(data.get("response", "")).strip()
        keywords = sanitize_keywords(raw_response.replace("_", " ").split())
        if not keywords:
            return LlavaResult(
                False,
                [],
                0.0,
                raw_response,
                "LLaVA returned no usable keywords.",
            )

        return LlavaResult(
            success=True,
            keywords=keywords[:4],
            confidence=0.85,
            raw_response=raw_response,
        )
