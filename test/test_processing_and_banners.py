import unittest
import requests
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.wuwa_calculator.app.banner_service import _normalise_banner, _parse_timestamp
from PySide6.QtWidgets import QApplication

from src.wuwa_calculator.app.pity_tracker import (
    CONVENE_DNS_ERROR_MESSAGE,
    ConveneLogCandidate,
    ClientLogReader,
    ConveneUrlExtractor,
    ConveneSyncWorker,
    LegacyPityTrackerWidget,
    NoticeManager,
    extract_convene_parameters,
    fetch_convene_records,
)
from src.wuwa_calculator.app.wuwa_processing import (
    RotationParameters,
    RotationStep,
    calculate_damage,
    calculate_rotation_step,
    parse_number,
)


class ProcessingAndBannerTests(unittest.TestCase):
    def test_client_log_locator_extracts_official_url_and_parameters(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            expected_url = (
                "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/"
                "index.html#/record?player_id=player1&record_id=record2"
            )
            log_path.write_text(f"noise {expected_url}", encoding="utf-8")

            url = ClientLogReader(log_path).get_convene_url()

            self.assertEqual(url, expected_url)
            self.assertEqual(
                extract_convene_parameters(url),
                ("player1", "record2"),
            )

    def test_debug_log_is_used_when_client_log_has_no_url(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            client_path = root / "Client.log"
            debug_path = root / "debug.log"
            client_path.write_text("no convene url", encoding="utf-8")
            debug_url = "https://aki-gm-resources.aki-game.com/aki/gacha/index.html#/record?playerId=p1&recordId=r2"
            debug_path.write_text(debug_url, encoding="utf-8")
            candidates = [
                (client_path, "client"),
                (debug_path, "debug"),
            ]
            typed_candidates = [
                ConveneLogCandidate(path, kind, root)
                for path, kind in candidates
            ]

            url = ConveneUrlExtractor().extract(typed_candidates)

            self.assertEqual(url, debug_url)

    def test_base_convene_page_is_rejected(self) -> None:
        self.assertIsNone(
            ConveneUrlExtractor.extract_url(
                "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html"
            )
        )

    def test_base_convene_page_with_query_is_rejected(self) -> None:
        self.assertIsNone(
            ConveneUrlExtractor.extract_url(
                "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html?foo=bar"
            )
        )

    def test_record_url_with_snake_case_parameters_is_accepted(self) -> None:
        url = (
            "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/"
            "index.html#/record?player_id=123&record_id=456"
        )

        self.assertEqual(ConveneUrlExtractor.extract_url(url), url)

    def test_record_url_with_camel_case_parameters_is_accepted(self) -> None:
        url = (
            "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/"
            "index.html#/record?playerId=123&recordId=456"
        )

        self.assertEqual(ConveneUrlExtractor.extract_url(url), url)

    def test_base_convene_page_does_not_replace_record_url(self) -> None:
        record_url = (
            "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/"
            "index.html#/record?player_id=123&record_id=456"
        )
        content = f"{record_url}\nhttps://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html"

        self.assertEqual(ConveneUrlExtractor.extract_url(content), record_url)

    def test_only_base_convene_page_is_reported_as_missing(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            log_path.write_text(
                "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                ClientLogReader(log_path).get_convene_url()

    def test_client_log_xor_content_is_decoded(self) -> None:
        expected = "https://aki-gm-resources.aki-game.net/aki/gacha/index.html#/record?player_id=p&record_id=r"
        encoded_values = []
        for target in expected.encode():
            candidate = target ^ 0xA5
            if not candidate & 1:
                candidate = target ^ 0xEF
            encoded_values.append(candidate)
        encoded = bytes(encoded_values)

        decoded = ConveneUrlExtractor.decode_client_log(encoded)

        self.assertEqual(decoded, expected)

    def test_missing_parameters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract_convene_parameters(
                "https://aki-gm-resources.aki-game.net/aki/gacha/index.html#/record?player_id=only"
            )

    def test_missing_log_is_reported_as_file_not_found(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "Client.log"
            with self.assertRaises(FileNotFoundError):
                ClientLogReader(missing_path).get_convene_url()

    def test_invalid_log_is_reported_without_crashing(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            log_path.write_bytes(b"\xff\xfe\x00corrupted")
            with self.assertRaises(ValueError):
                ClientLogReader(log_path).get_convene_url()

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

    def test_convene_sync_worker_fetches_latest_log_url(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            log_path.write_text(
                "old https://aki-gm-resources.example/old/record?token=old\n"
                "latest https://aki-gm-resources.example/latest/record?token=new",
                encoding="utf-8",
            )
            response = Mock()
            response.status_code = 200
            response.text = '{"data": [{"rarity": 5, "name": "Test"}]}'
            response.json.return_value = {"data": [{"rarity": 5, "name": "Test"}]}
            worker = ConveneSyncWorker(log_path)
            received: list[object] = []
            errors: list[str] = []
            worker.success_signal.connect(received.append)
            worker.error_signal.connect(errors.append)

            with patch("src.wuwa_calculator.app.pity_tracker.requests.get", return_value=response) as get:
                worker.run()

            get.assert_called_once_with(
                "https://aki-gm-resources.example/latest/record?token=new",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/json, text/plain, */*",
                },
                timeout=15,
            )
            self.assertEqual(received, [{"data": [{"rarity": 5, "name": "Test"}]}])
            self.assertEqual(errors, [])

    def test_convene_sync_worker_rejects_empty_api_response(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            log_path.write_text("https://aki-gm-resources.example/latest/record?token=x", encoding="utf-8")
            response = Mock(text="")
            worker = ConveneSyncWorker(log_path)
            errors: list[str] = []
            worker.error_signal.connect(errors.append)

            with patch("src.wuwa_calculator.app.pity_tracker.requests.get", return_value=response):
                worker.run()

            self.assertEqual(errors, ["Sessão expirada. Acesse o Convene no jogo para revalidar."])

    def test_convene_sync_worker_rejects_expired_json_response(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            log_path.write_text("https://aki-gm-resources.example/latest/record?token=x", encoding="utf-8")
            response = Mock(text="not-json")
            worker = ConveneSyncWorker(log_path)
            errors: list[str] = []
            worker.error_signal.connect(errors.append)

            with patch("src.wuwa_calculator.app.pity_tracker.requests.get", return_value=response):
                worker.run()

            self.assertEqual(
                errors,
                ["Sessão expirada. Acesse o Convene no jogo para revalidar."],
            )

    def test_convene_sync_worker_reports_http_405(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            log_path.write_text("https://aki-gm-resources.example/latest/record?token=x", encoding="utf-8")
            response = Mock(status_code=405, text="Method Not Allowed")
            worker = ConveneSyncWorker(log_path)
            errors: list[str] = []
            worker.error_signal.connect(errors.append)

            with patch("src.wuwa_calculator.app.pity_tracker.requests.get", return_value=response):
                worker.run()

            self.assertEqual(
                errors,
                ["Erro HTTP 405: Método de requisição recusado pelo servidor da Kuro."],
            )

    def test_fetch_convene_records_posts_each_banner_pool(self) -> None:
        response = Mock(status_code=200, text='{"code": 0, "data": [{"rarity": 5}]}')
        with patch("src.wuwa_calculator.app.pity_tracker.requests.post", return_value=response) as post:
            records = fetch_convene_records(
                "https://aki-gm-resources.example/record?player_id=player&record_id=record"
            )

        self.assertEqual(len(records), 8)
        self.assertEqual(post.call_count, 8)
        first_payload = post.call_args_list[0].kwargs["json"]
        self.assertEqual(first_payload["playerId"], "player")
        self.assertEqual(first_payload["recordId"], "record")
        self.assertEqual(first_payload["cardPoolType"], 1)

    def test_legacy_tracker_derives_recent_history_from_cronological_records(self) -> None:
        app = QApplication.instance() or QApplication([])
        records = [
            {"timestamp": "2024-01-01T00:00:00Z", "name": "pull-01", "rarity": 4, "pool": "resonator"},
            {"timestamp": "2024-01-02T00:00:00Z", "name": "pull-02", "rarity": 3, "pool": "resonator"},
            {"timestamp": "2024-01-03T00:00:00Z", "name": "five-01", "rarity": 5, "pool": "resonator"},
            {"timestamp": "2024-01-04T00:00:00Z", "name": "pull-04", "rarity": 4, "pool": "resonator"},
            {"timestamp": "2024-01-05T00:00:00Z", "name": "five-02", "rarity": 5, "pool": "resonator"},
            {"timestamp": "2024-01-06T00:00:00Z", "name": "pull-06", "rarity": 4, "pool": "resonator"},
            {"timestamp": "2024-01-07T00:00:00Z", "name": "five-03", "rarity": 5, "pool": "resonator"},
        ]

        widget = LegacyPityTrackerWidget()
        widget._update_state_from_records(records)

        self.assertEqual(widget.state.five_star_history, [3, 2, 2])
        self.assertEqual(
            widget.state.recent_convene_details,
            [
                "five-01 (5★)",
                "pull-04 (4★)",
                "five-02 (5★)",
                "pull-06 (4★)",
                "five-03 (5★)",
            ],
        )

    def test_notice_manager_normalizes_kuro_official_news_payload(self) -> None:
        payload = {
            "data": {
                "list": [{
                    "id": "42",
                    "title": "Patch notes",
                    "categoryName": "Avisos",
                    "createTime": "2026-09-09T10:00:00Z",
                    "coverUrl": "https://example.com/banner.png",
                }]
            }
        }

        notice = NoticeManager().normalize(payload)[0]

        self.assertEqual(notice["category"], "Avisos")
        self.assertEqual(notice["date"], "09-09")
        self.assertEqual(notice["image_url"], "https://example.com/banner.png")
        self.assertEqual(
            notice["content_url"],
            "https://wutheringwaves.kurogames.com/pt/main/news/detail/42",
        )

    def test_extract_convene_parameters_reads_hash_fragment(self) -> None:
        player_id, record_id = extract_convene_parameters(
            "https://aki-gm-resources.example/aki/gacha/index.html/#/record?"
            "player_id=playerhash&record_id=recordhash&cardPoolType=1"
        )

        self.assertEqual(player_id, "playerhash")
        self.assertEqual(record_id, "recordhash")

    def test_extract_convene_parameters_cleans_encoded_camel_case_url(self) -> None:
        player_id, record_id = extract_convene_parameters(
            "  https://aki-gm-resources.example/gacha/#/record?"
            "playerId=Player123%0D%0A&recordId=Record456  \r\n"
        )

        self.assertEqual(player_id, "Player123")
        self.assertEqual(record_id, "Record456")

    def test_fetch_convene_records_falls_back_after_dns_failure(self) -> None:
        response = Mock(status_code=200, text='{"code": 0, "data": [{"rarity": 5}]}')

        def post(endpoint: str, **kwargs):
            if endpoint == "https://gm-server-gacha.aki-game.net/gacha/getGachaRecord":
                raise requests.exceptions.ConnectionError("NameResolutionError")
            return response

        with patch("src.wuwa_calculator.app.pity_tracker.requests.post", side_effect=post) as mocked_post:
            records = fetch_convene_records(
                "https://aki-gm-resources.example/gacha?player_id=player&record_id=record"
            )

        self.assertEqual(len(records), 8)
        self.assertEqual(mocked_post.call_count, 16)
        self.assertEqual(mocked_post.call_args_list[1].args[0], "https://aki-gm-resources-oversea.aki-game.net/gacha/getGachaRecord")

    def test_fetch_convene_records_falls_back_after_http_405(self) -> None:
        response = Mock(status_code=200, text='{"code": 0, "data": [{"rarity": 5}]}')

        def post(endpoint: str, **kwargs):
            if endpoint == "https://gm-server-gacha.aki-game.net/gacha/getGachaRecord":
                return Mock(status_code=405, text="Method Not Allowed")
            return response

        with patch("src.wuwa_calculator.app.pity_tracker.requests.post", side_effect=post) as mocked_post:
            records = fetch_convene_records(
                "https://aki-gm-resources.example/gacha?player_id=player&record_id=record"
            )

        self.assertEqual(len(records), 8)
        self.assertEqual(mocked_post.call_count, 16)

    def test_fetch_convene_records_uses_get_when_post_is_not_allowed(self) -> None:
        post_response = Mock(status_code=405, text="Method Not Allowed")
        get_response = Mock(status_code=200, text='{"code": 0, "data": [{"rarity": 5}]}')
        with patch(
            "src.wuwa_calculator.app.pity_tracker.requests.post",
            return_value=post_response,
        ), patch(
            "src.wuwa_calculator.app.pity_tracker.requests.get",
            return_value=get_response,
        ) as get:
            records = fetch_convene_records(
                "https://aki-gm-resources.example/gacha?player_id=player&record_id=record"
            )

        self.assertEqual(len(records), 8)
        self.assertEqual(get.call_count, 8)
        self.assertEqual(get.call_args.kwargs["params"]["playerId"], "player")
        self.assertEqual(get.call_args.kwargs["params"]["recordId"], "record")

    def test_fetch_convene_records_extracts_nested_api_record_shapes(self) -> None:
        response = Mock(
            status_code=200,
            text='{"code": 0, "data": {"result": {"rows": [{"rarity": 5, "name": "Qingxiao"}]}}}',
        )
        with patch("src.wuwa_calculator.app.pity_tracker.requests.post", return_value=response):
            records = fetch_convene_records(
                "https://aki-gm-resources.example/gacha?player_id=player&record_id=record"
            )

        self.assertEqual(len(records), 8)
        self.assertEqual(records[0]["name"], "Qingxiao")

    def test_fetch_convene_records_reports_dns_failure_after_all_fallbacks(self) -> None:
        with patch(
            "src.wuwa_calculator.app.pity_tracker.requests.post",
            side_effect=requests.exceptions.ConnectionError("NameResolutionError"),
        ):
            with self.assertRaisesRegex(requests.exceptions.ConnectionError, "Erro de Conexão/DNS"):
                fetch_convene_records(
                    "https://aki-gm-resources.example/gacha?player_id=player&record_id=record"
                )

    def test_client_log_reader_works_with_game_closed(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "Client.log"
            expected_url = (
                "https://aki-gm-resources.example/record?player_id=player&record_id=record"
            )
            log_path.write_text(f"Convene Record URL: {expected_url}", encoding="utf-8")

            self.assertEqual(ClientLogReader(log_path).get_convene_url(), expected_url)

if __name__ == "__main__":
    unittest.main()
