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
        self.assertEqual(clean_number("X18%"), 18.0)

    def test_extract_stats_and_character(self) -> None:
        text = "Qingxiao\nATK 1,500\nCrit Rate: 60%\nCrit DMG: 180%"

        self.assertEqual(extract_stats_from_text(text), {
            "atk": 1500.0,
            "crit_rate": 60.0,
            "crit_dmg": 180.0,
        })
        self.assertEqual(identify_character(text), "qingxiao")

    def test_extract_stats_ignores_skills_energy_and_damage_bonuses(self) -> None:
        text = (
            "Augusta\n"
            "ATK 2,400\n"
            "HP 10,000\n"
            "DEF 1,200\n"
            "Crit Rate 68%\n"
            "Crit DMG 250%\n"
            "Energy Regen 125%\n"
            "Forte Circuit 180%\n"
            "Resonance Skill DMG Bonus 220%\n"
        )

        self.assertEqual(extract_stats_from_text(text), {
            "atk": 2400.0,
            "hp": 10000.0,
            "def": 1200.0,
            "crit_rate": 68.0,
            "crit_dmg": 250.0,
        })

    def test_echo_parser_sanitizes_ocr_noise_and_keeps_cost_set(self) -> None:
        text = (
            "Tempest Echo\n"
            "Cost 4\n"
            "Set: Gale Circuit\n"
            "ATK X18%\n"
            "Crit Rate +7.9%\n"
            "HP +10\n"
        )

        parsed = __import__('src.wuwa_calculator.utils.ocr', fromlist=['identify_echo_cards']).identify_echo_cards(text)

        self.assertTrue(parsed)
        echo = parsed[0]
        self.assertEqual(echo["cost"], 4)
        self.assertIn("Gale", str(echo["set_bonus"]))
        self.assertIn("ATK", str(echo["main_stat"]))
        self.assertNotIn("X", str(echo["main_stat"]))
        self.assertIn("7.9", " ".join(str(v) for v in echo["attributes"]))
        self.assertEqual(extract_stats_from_text("ATK X18%\nCrit Rate +7.9%"), {
            "atk": 18.0,
            "crit_rate": 7.9,
        })


if __name__ == "__main__":
    unittest.main()
