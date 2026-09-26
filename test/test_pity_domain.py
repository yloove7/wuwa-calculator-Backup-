import unittest

from src.wuwa_calculator.domain.pity import (
    calculate_pity_state,
    format_recent_record,
    record_pool,
    record_sort_key,
)


class PityDomainTests(unittest.TestCase):
    def test_calculates_chronological_pity_and_resets_after_five_star(self):
        records = [
            {"timestamp": "2026-01-03T00:00:00Z", "name": "late", "rarity": 4, "pool": "resonator"},
            {"timestamp": "2026-01-01T00:00:00Z", "name": "first", "rarity": 3, "pool": "resonator"},
            {"timestamp": "2026-01-02T00:00:00Z", "name": "five", "rarity": 5, "pool": "resonator"},
        ]

        state = calculate_pity_state(records)

        self.assertEqual(state.resonator, 1)
        self.assertEqual(state.five_star_history, [2])

    def test_counts_four_stars(self):
        state = calculate_pity_state([
            {"timestamp": 1, "rarity": 4, "pool": "resonator"},
            {"timestamp": 2, "rarity": 4, "pool": "weapon"},
            {"timestamp": 3, "rarity": 3, "pool": "weapon"},
        ])
        self.assertEqual(state.four_star_total, 2)

    def test_excludes_explicit_non_pull_from_pity_and_total(self):
        state = calculate_pity_state([
            {"timestamp": 1, "rarity": 3, "pool": "resonator"},
            {"timestamp": 2, "is_pull": False, "record_url": "metadata-only"},
        ])

        self.assertEqual(state.total_registered, 1)
        self.assertEqual(state.resonator, 1)
        self.assertEqual(
            state.recent_convene_details,
            [format_recent_record({"rarity": 3})],
        )

    def test_non_pull_only_history_does_not_create_pity(self):
        state = calculate_pity_state([
            {"timestamp": 1, "is_pull": False, "record_url": "metadata-1"},
            {"timestamp": 2, "is_pull": False, "record_url": "metadata-2"},
        ])

        self.assertEqual(state.total_registered, 0)
        self.assertEqual(state.resonator, 0)
        self.assertEqual(state.five_star_history, [])
        self.assertEqual(state.recent_convene_details, [])

    def test_non_pulls_do_not_contaminate_pity_across_pools(self):
        state = calculate_pity_state([
            {"timestamp": 1, "rarity": 3, "pool": "resonator"},
            {"timestamp": 2, "rarity": 3, "pool": "weapon"},
            {"timestamp": 3, "is_pull": False, "pool": "resonator", "record_url": "r"},
            {"timestamp": 4, "is_pull": False, "pool": "weapon", "record_url": "w"},
            {"timestamp": 5, "is_pull": False, "pool": "standard character", "record_url": "sc"},
            {"timestamp": 6, "rarity": 3, "pool": "standard character"},
            {"timestamp": 7, "is_pull": False, "pool": "standard weapon", "record_url": "sw"},
            {"timestamp": 8, "rarity": 3, "pool": "standard weapon"},
        ])

        self.assertEqual(state.total_registered, 4)
        self.assertEqual(state.resonator, 1)
        self.assertEqual(state.weapon, 1)
        self.assertEqual(state.standard_character, 1)
        self.assertEqual(state.standard_weapon, 1)

    def test_keeps_five_star_sequence(self):
        state = calculate_pity_state([
            {"timestamp": 1, "rarity": 3, "pool": "resonator"},
            {"timestamp": 2, "rarity": 5, "pool": "resonator"},
            {"timestamp": 3, "rarity": 4, "pool": "resonator"},
            {"timestamp": 4, "rarity": 5, "pool": "resonator"},
        ])
        self.assertEqual(state.five_star_history, [2, 2])

    def test_separates_pools(self):
        state = calculate_pity_state([
            {"timestamp": 1, "rarity": 3, "pool": "resonator"},
            {"timestamp": 2, "rarity": 3, "pool": "weapon"},
            {"timestamp": 3, "rarity": 3, "pool": "standard", "name": "Character"},
            {"timestamp": 4, "rarity": 3, "pool": "standard weapon", "name": "Weapon"},
        ])
        self.assertEqual(state.resonator, 1)
        self.assertEqual(state.weapon, 1)
        self.assertEqual(state.standard_character, 1)
        self.assertEqual(state.standard_weapon, 1)

    def test_sort_key_orders_iso_and_unix_values(self):
        records = [
            {"timestamp": "2026-01-02T00:00:00Z"},
            {"timestamp": 1},
            {"timestamp": "invalid"},
        ]
        ordered = sorted(records, key=record_sort_key)
        self.assertEqual(ordered[0]["timestamp"], 1)
        self.assertEqual(ordered[-1]["timestamp"], "invalid")

    def test_recent_details_keep_latest_five_after_sorting(self):
        records = [
            {"timestamp": index, "name": f"pull-{index}", "rarity": 3}
            for index in range(7)
        ]
        state = calculate_pity_state(records)
        self.assertEqual(
            state.recent_convene_details,
            [f"pull-{index} (3★)" for index in range(2, 7)],
        )

    def test_empty_history_returns_empty_state(self):
        state = calculate_pity_state([])
        self.assertEqual(state.resonator, 0)
        self.assertEqual(state.five_star_history, [])
        self.assertEqual(state.recent_convene_details, [])
        self.assertEqual(state.total_registered, 0)

    def test_missing_fields_match_existing_fallbacks(self):
        state = calculate_pity_state([{}, {"timestamp": 1, "name": "Unknown"}])
        self.assertEqual(state.total_registered, 2)
        self.assertEqual(state.recent_convene_details, ["Unknown (?★)", "Convene (?★)"])
        self.assertEqual(record_pool({}), "resonator")
        self.assertEqual(format_recent_record("raw"), "raw")


if __name__ == "__main__":
    unittest.main()
