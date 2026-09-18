import unittest

from src.wuwa_calculator.app.banner_service import _normalise_banner, _parse_timestamp
from src.wuwa_calculator.app.wuwa_processing import (
    RotationParameters,
    RotationStep,
    calculate_damage,
    calculate_rotation_step,
    parse_number,
)


class ProcessingAndBannerTests(unittest.TestCase):
    def test_damage_calculation_uses_hits_casts_and_duration(self) -> None:
        result = calculate_damage(
            attack=1000,
            scaling=100,
            flat_bonus=0,
            crit_rate=0,
            crit_damage=150,
            hits=2,
            enemy_defense=0,
            resistance_reduction=0,
            rotation_casts=2,
            rotation_seconds=4,
        )

        self.assertEqual(result.total_cast, 2000)
        self.assertEqual(result.rotation_damage, 4000)
        self.assertEqual(result.dps, 1000)

    def test_rotation_step_applies_bonuses(self) -> None:
        result = calculate_rotation_step(
            RotationParameters(
                base_attack=1000,
                elemental_bonus=20,
                defense_factor=0.5,
            ),
            RotationStep("Skill", skill_modifier=100, hits=2),
            duration=2,
        )

        self.assertEqual(result.damage_per_hit, 1050)
        self.assertEqual(result.total_damage, 2100)
        self.assertEqual(result.dps, 1050)

    def test_number_and_timestamp_parsers(self) -> None:
        self.assertEqual(parse_number("1,25"), 1.25)
        self.assertEqual(parse_number("invalid", default=7), 7)
        self.assertEqual(_parse_timestamp("2026-09-10T10:00:00Z"), "2026-09-10T10:00:00+00:00")

    def test_banner_normalization_accepts_nested_character(self) -> None:
        banner = _normalise_banner({
            "character": {
                "name": "Qingxiao",
                "image": "https://i.imgur.com/lq6O5Vo.jpeg",
            },
            "endDate": "2026-09-10T10:00:00Z",
        })

        self.assertEqual(banner["name"], "Qingxiao")
        self.assertEqual(banner["image_url"], "https://i.imgur.com/lq6O5Vo.jpeg")
        self.assertEqual(banner["ends_at"], "2026-09-10T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
