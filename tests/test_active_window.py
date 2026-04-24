from __future__ import annotations

import unittest

from active_window import _detect_app_name, _extract_title_keywords


class ActiveWindowTests(unittest.TestCase):
    def test_copilot_page_title_beats_browser_process_name(self) -> None:
        app_name = _detect_app_name("New chat - GitHub Copilot", "chrome")

        self.assertEqual(app_name, "copilot")

    def test_copilot_title_keywords_include_actual_page_context(self) -> None:
        keywords = _extract_title_keywords(
            "New chat - GitHub Copilot",
            "copilot",
        )

        self.assertIn("copilot", keywords)
        self.assertIn("github", keywords)
        self.assertIn("chat", keywords)


if __name__ == "__main__":
    unittest.main()
