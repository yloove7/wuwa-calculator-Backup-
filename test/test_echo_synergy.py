import unittest

from src.wuwa_calculator.app.teams_tab import CharacterEquip, EchoItem, EchoSynergyEngine


class EchoSynergyEngineTests(unittest.TestCase):
    def test_unique_names_in_same_set_count_once(self) -> None:
        char = CharacterEquip(
            char_name="Test Character",
            echoes=[
                EchoItem(name="Aero Drake", set_name="Sierra Gale"),
                EchoItem(name="Aero Drake", set_name="Sierra Gale"),
                EchoItem(name="Sky Rook", set_name="Sierra Gale"),
                EchoItem(name="Cloudfang", set_name="Sierra Gale"),
                EchoItem(name="Gale Howler", set_name="Sierra Gale"),
            ],
        )

        result = EchoSynergyEngine.calculate_character_sets(char)
        self.assertIn("Sierra Gale", result)
        self.assertEqual(result["Sierra Gale"]["tier"], "2P (Parcial)")

    def test_mixed_sets_can_activate_two_2p_bonus(self) -> None:
        char = CharacterEquip(
            char_name="Test Character",
            echoes=[
                EchoItem(name="A", set_name="Sierra Gale"),
                EchoItem(name="B", set_name="Sierra Gale"),
                EchoItem(name="C", set_name="Molten Rift"),
                EchoItem(name="D", set_name="Molten Rift"),
                EchoItem(name="E", set_name="Moonlit Clouds"),
            ],
        )

        result = EchoSynergyEngine.calculate_character_sets(char)
        self.assertEqual(len(result), 2)
        self.assertIn("Sierra Gale", result)
        self.assertIn("Molten Rift", result)
        self.assertIn("2P", result["Sierra Gale"]["tier"])
        self.assertIn("2P", result["Molten Rift"]["tier"])


if __name__ == "__main__":
    unittest.main()
