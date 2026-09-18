import unittest

from src.wuwa_calculator.utils.ocr import (
    clean_number,
    extract_stats_from_text,
    identify_character,
)


class OcrParserTests(unittest.TestCase):
    def test_clean_number_supports_common_locale_formats(self) -> None:
        self.assertEqual(clean_number("1.234,5"), 1234.5)
        self.assertEqual(clean_number("1,500"), 1500)
        self.assertEqual(clean_number("1,25"), 1.25)

    def test_extract_stats_and_character(self) -> None:
        text = "Qingxiao\nATK 1,500\nCrit Rate: 60%\nCrit DMG: 180%"

        self.assertEqual(extract_stats_from_text(text), {
            "atk": 1500.0,
            "crit_rate": 60.0,
            "crit_dmg": 180.0,
        })
        self.assertEqual(identify_character(text), "qingxiao")


if __name__ == "__main__":
    unittest.main()
