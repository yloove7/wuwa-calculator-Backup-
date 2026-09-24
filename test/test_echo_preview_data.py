import unittest

from src.wuwa_calculator.app.image_import.echo_preview_data import format_echo_preview_data


class EchoPreviewDataTests(unittest.TestCase):
    def test_formats_complete_echo(self) -> None:
        self.assertEqual(
            format_echo_preview_data({
                "name": "Tempest Mephis",
                "attributes": ["ATK +18%", "Crit Rate +7.9%", "HP +10"],
                "main_stat": "ATK +18%",
                "sub_stats": ["Crit Rate +7.9%", "HP +10"],
                "cost": 4,
                "set_bonus": "Gale Circuit",
            }),
            (
                "Tempest Mephis",
                "Cost: 4\nSet: Gale Circuit\nMain: ATK +18%\n"
                "Sub-stats: Crit Rate +7.9%; HP +10",
            ),
        )

    def test_missing_fields_use_existing_fallbacks(self) -> None:
        self.assertEqual(
            format_echo_preview_data({}),
            ("Echo", "Cost: --\nSet: --\nMain: --\nSub-stats: --"),
        )

    def test_attributes_supply_main_and_sub_stats_when_specific_fields_are_absent(self) -> None:
        self.assertEqual(
            format_echo_preview_data({"attributes": ["Main", "Sub 1", "Sub 2"]}),
            ("Echo", "Cost: --\nSet: --\nMain: Main\nSub-stats: Sub 1; Sub 2"),
        )

    def test_preserves_existing_none_and_unexpected_type_behavior(self) -> None:
        self.assertEqual(
            format_echo_preview_data({
                "name": None,
                "attributes": "not a list",
                "main_stat": None,
                "sub_stats": "not a list",
                "cost": 0,
                "set_bonus": None,
            }),
            ("None", "Cost: --\nSet: None\nMain: None\nSub-stats: --"),
        )


if __name__ == "__main__":
    unittest.main()
