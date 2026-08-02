import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UIColorConsistencyTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        cls.template = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    def test_theme_swatches_match_applied_theme_tokens(self) -> None:
        expected = {
            "blue": "#2196f3",
            "green": "#07c160",
            "coral": "#ff715b",
            "violet": "#7c62e8",
            "pink": "#e85d9e",
            "cyan": "#00a6a6",
        }

        for name, color in expected.items():
            with self.subTest(theme=name):
                self.assertIn(f"--theme-{name}: {color};", self.styles)
                self.assertIn(f'body[data-accent="{name}"]', self.styles)
                self.assertIn(
                    f".color-dot.{name} {{ background: var(--theme-{name}); }}",
                    self.styles,
                )
                self.assertIn(f'data-accent="{name}"', self.template)

    def test_avatar_swatches_match_saved_avatar_values(self) -> None:
        expected = {
            "blue": "#5b8def",
            "green": "#07c160",
            "coral": "#f08a5d",
            "violet": "#8a6de9",
            "pink": "#df6fa8",
            "cyan": "#43b7b7",
        }

        for name, color in expected.items():
            with self.subTest(avatar=name):
                self.assertIn(f"--avatar-{name}: {color};", self.styles)
                self.assertIn(
                    f".profile-color-dot.{name} {{ --avatar-swatch: var(--avatar-{name}); background: var(--avatar-swatch); }}",
                    self.styles,
                )
                self.assertIn(f'data-profile-color="{color}"', self.template)

    def test_device_avatar_allows_saved_inline_color(self) -> None:
        device_avatar_rule = self.styles.split(".device-avatar {", 2)[-1].split("}", 1)[0]
        self.assertNotIn("!important", device_avatar_rule)

    def test_theme_swatch_outlines_only_highlight_selected_color(self) -> None:
        swatch_rule = self.styles.split(".color-dot {", 1)[1].split("}", 1)[0]
        active_rule = self.styles.split(".color-dot.active {", 1)[1].split("}", 1)[0]
        self.assertIn("border: 3px solid transparent;", swatch_rule)
        self.assertIn("box-shadow: none;", swatch_rule)
        self.assertIn("border-color: var(--surface);", active_rule)
        self.assertIn("box-shadow: 0 0 0 2px var(--accent);", active_rule)

    def test_avatar_and_theme_rows_have_six_aligned_color_positions(self) -> None:
        avatar_group = self.template.split('role="group" aria-label="头像颜色"', 1)[1].split("</div>", 1)[0]
        theme_group = self.template.split('role="group" aria-label="主题颜色"', 1)[1].split("</div>", 1)[0]
        avatar_order = re.findall(r"profile-color-dot ([a-z]+)", avatar_group)
        theme_order = re.findall(r"color-dot ([a-z]+)", theme_group)
        self.assertEqual(avatar_order, ["blue", "green", "coral", "violet", "pink", "cyan"])
        self.assertEqual(theme_order, avatar_order)

    def test_avatar_selected_outline_uses_avatar_color_not_theme_color(self) -> None:
        active_rule = self.styles.rsplit(".profile-color-dot.active {", 1)[1].split("}", 1)[0]
        self.assertIn("box-shadow: 0 0 0 2px var(--avatar-swatch);", active_rule)
        self.assertNotIn("var(--accent)", active_rule)


if __name__ == "__main__":
    unittest.main()
