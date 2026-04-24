from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime

from nlp_namer import build_filename, extract_keywords, sanitize_fragment
from settings import AppSettings


class NlpNamerTests(unittest.TestCase):
    def test_trusted_window_keywords_survive_low_ocr_confidence(self) -> None:
        settings = replace(
            AppSettings.defaults(),
            confidence_threshold=0.8,
            append_timestamp=False,
        )
        keywords = extract_keywords(
            raw_text="",
            header_text="",
            active_window_keywords=["gpt4", "chat"],
        )

        result = build_filename(
            keywords,
            settings,
            ".png",
            confidence=0.0,
            now=datetime(2026, 4, 24, 12, 0, 0),
        )

        self.assertFalse(result.used_fallback)
        self.assertEqual(result.filename, "gpt4_chat.png")

    def test_sanitize_fragment_keeps_safe_dots_only_inside_name(self) -> None:
        self.assertEqual(
            sanitize_fragment("  API.Error: screen-shot.PNG  "),
            "api.error_screen_shot.png",
        )
        self.assertEqual(sanitize_fragment("..."), "")


if __name__ == "__main__":
    unittest.main()
