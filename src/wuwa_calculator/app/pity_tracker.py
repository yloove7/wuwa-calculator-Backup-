"""Compact real-time pity tracker UI fed by an authorized local source."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import os
import sys
import re
import json
import subprocess
import requests
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    Property,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QTimer,
    QObject,
    QPoint,
    QRectF,
    QThread,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.wuwa_calculator.app.security_policy import allows_remote_content
from src.wuwa_calculator.app.components import circular_pixmap
from src.wuwa_calculator.app.convene.presentation import pity_progress_bar
from src.wuwa_calculator.app.styles import wallpaper_palette
from src.wuwa_calculator.domain.pity import (
    PityState,
    calculate_pity_state,
    extract_records,
    format_recent_record,
    record_pool,
    record_sort_key,
)
from src.wuwa_calculator.storage.convene_storage import (
    ConveneJsonImportReport,
    ConveneStorageManager,
)
from src.wuwa_calculator.utils.convene_datetime import (
    KURO_TIMEZONE,
    parse_convene_datetime,
)
WUWA_TRACKER_IMPORT_COMMAND = (
    'iwr -UseBasicParsing -Headers @{"User-Agent"="Mozilla/5.0"} '
    "https://raw.githubusercontent.com/wuwatracker/wuwatracker/"
    "747a48b1b994baa9c372a4fb933ea7588428bd4b/import.ps1 | iex"
)
EVENT_RESONATOR_BANNER_URL = "https://i.imgur.com/JrRW9Bt.jpeg"
SIGNATURE_WEAPON_BANNER_URL = "https://i.imgur.com/metoowt.jpeg"
CONVENE_URL_PREFIX = "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html#"
CONVENE_LOG_PATH = Path(
    r"D:\Wuthering Waves\Wuthering Waves Game\Client\Saved\Logs\Client.log"
)
KURO_NEWS_API_URL = "https://wutheringwaves.kurogames.com/api/news/list"
KURO_NEWS_DETAIL_URL = "https://wutheringwaves.kurogames.com/pt/main/news/detail/"
CONVENE_LOG_URL_RE = re.compile(r"https://aki-gm-resources[^\s\"']+")
CONVENE_GACHA_URL_RE = re.compile(r"https?://[^\s\"]*?/record[^\s\"]*", re.IGNORECASE)
CONVENE_RECORD_URL_RE = re.compile(
    r"https://aki-gm-resources(-oversea)?\.aki-game\.(net|com)/"
    r"aki/gacha/index\.html#/record[^\"\s]*",
    re.IGNORECASE,
)
CONVENE_DEBUG_RELATIVE_PATH = Path(
    r"Client\Binaries\Win64\ThirdParty\KrPcSdk_Global\KRSDKRes\KRSDKWebView\debug.log"
)
CONVENE_CLIENT_RELATIVE_PATH = Path(r"Client\Saved\Logs\Client.log")
CONVENE_URL_NOT_FOUND_MESSAGE = (
    "URL não encontrada. Abra a tela de Convene no jogo e tente novamente."
)
CONVENE_DNS_ERROR_MESSAGE = (
    "Erro de Conexão/DNS: Não foi possível alcançar o servidor da Kuro Games. "
    "Verifique sua internet ou firewall."
)
BRAVE_CDP_URL = "http://127.0.0.1:9222/json/list"
KURO_RECORD_API_URL = "https://gmserver-api.aki-game2.net/gacha/record/query"
CONVENE_PLAYER_ID_RE = re.compile(
    r"(?:player_id|playerId)=([a-zA-Z0-9]+)", re.IGNORECASE
)
CONVENE_RECORD_ID_RE = re.compile(
    r"(?:record_id|recordId)=([a-zA-Z0-9]+)", re.IGNORECASE
)
CONVENE_SERVER_ID_RE = re.compile(
    r"(?:svr_id|serverId)=([a-zA-Z0-9]+)", re.IGNORECASE
)
CONVENE_CARD_POOL_ID_RE = re.compile(
    r"(?:resources_id|resourcesId|cardPoolId|card_pool_id)=([a-zA-Z0-9]+)",
    re.IGNORECASE,
)
CONVENE_LANGUAGE_CODE_RE = re.compile(
    r"(?:lang|languageCode|language_code)=([a-zA-Z0-9-]+)", re.IGNORECASE
)


@dataclass(frozen=True)
class ConveneLogCandidate:
    path: Path
    kind: str
    install_path: Path | None = None


@dataclass(frozen=True)
class ConveneCaptureContext:
    """Provenance and identity discovered for one explicit capture attempt."""

    source_url: str
    player_id: str
    record_id: str
    svr_id: str
    resources_id: str
    lang: str
    log_path: Path | None
    log_mtime: float | None
    discovered_at: str
    discovery_source: str
    is_new_capture: bool = True


class ConveneLogLocator:
    """Find existing Wuthering Waves logs without requiring the game to run."""

    def __init__(self, log_path: str | Path | None = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else None

    def locate(self) -> list[ConveneLogCandidate]:
        candidates: list[ConveneLogCandidate] = []
        seen: set[Path] = set()

        def add(path: Path, kind: str, install_path: Path | None = None) -> None:
            normalized = path.expanduser()
            if normalized in seen or not normalized.is_file():
                return
            seen.add(normalized)
            candidates.append(ConveneLogCandidate(normalized, kind, install_path))

        if self.log_path is not None:
            install_path = self._find_install_root(self.log_path)
            if self.log_path.name.casefold() == "debug.log":
                add(self.log_path, "debug", install_path)
                if install_path is not None:
                    add(install_path / CONVENE_CLIENT_RELATIVE_PATH, "client", install_path)
            else:
                add(self.log_path, "client", install_path)
                if install_path is not None:
                    add(install_path / CONVENE_DEBUG_RELATIVE_PATH, "debug", install_path)
            return candidates

        user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", user_profile / "AppData" / "Local"))
        add(
            user_profile / "AppData" / "LocalLow" / "Kuro Game" /
            "Wuthering Waves" / "Saved" / "Logs" / "Client.log",
            "client",
        )
        add(local_app_data / "Wuthering Waves" / "Saved" / "Logs" / "Client.log", "client")

        install_roots = self._install_roots()
        for root in install_roots:
            add(root / CONVENE_CLIENT_RELATIVE_PATH, "client", root)
            add(root / CONVENE_DEBUG_RELATIVE_PATH, "debug", root)

        return candidates

    @staticmethod
    def _find_install_root(path: Path) -> Path | None:
        for parent in (path, *path.parents):
            if parent.name.casefold() == "client":
                return parent.parent
        return None

    @staticmethod
    def _install_roots() -> list[Path]:
        roots: list[Path] = []
        configured = os.environ.get("TETHYS_WUWA_INSTALL_PATH", "").strip()
        if configured:
            roots.append(Path(configured))

        for drive in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_root = Path(f"{drive}:\\")
            for relative in (
                Path("Wuthering Waves") / "Wuthering Waves Game",
                Path("Wuthering Waves Game"),
                Path("SteamLibrary/steamapps/common/Wuthering Waves"),
                Path("SteamLibrary/steamapps/common/Wuthering Waves/Wuthering Waves Game"),
                Path("Program Files/Epic Games/WutheringWavesj3oFh"),
                Path("Program Files/Epic Games/WutheringWavesj3oFh/Wuthering Waves Game"),
                Path("Program Files/Wuthering Waves/Wuthering Waves Game"),
            ):
                candidate = drive_root / relative
                if candidate.is_dir():
                    roots.append(candidate)
        return list(dict.fromkeys(roots))


class ConveneUrlExtractor:
    """Read logs and extract the newest usable Convene Record URL."""

    @staticmethod
    def read_shared_bytes(path: Path) -> bytes:
        with path.open("rb") as file:
            return file.read()

    @staticmethod
    def decode_client_log(data: bytes) -> str:
        decoded = bytearray(data)
        for index, value in enumerate(decoded):
            decoded[index] = value ^ (0xA5 if value & 1 else 0xEF)
        return bytes(decoded).decode("utf-8", errors="ignore")

    @staticmethod
    def extract_url(content: str) -> str | None:
        matches = list(CONVENE_RECORD_URL_RE.finditer(content))
        if matches:
            return matches[-1].group(0)
        legacy_matches = CONVENE_GACHA_URL_RE.findall(content)
        return legacy_matches[-1] if legacy_matches else None

    def extract_from_candidate(self, candidate: ConveneLogCandidate) -> str | None:
        raw = self.read_shared_bytes(candidate.path)
        contents = [raw.decode("utf-8", errors="ignore")]
        if candidate.kind == "client":
            contents.insert(0, self.decode_client_log(raw))
        for content in contents:
            url = self.extract_url(content)
            if url:
                return url
        return None

    def extract(self, candidates: list[ConveneLogCandidate]) -> str | None:
        """Extract a URL without requiring every API context parameter."""
        ranked = sorted(
            candidates,
            key=lambda item: item.path.stat().st_mtime,
            reverse=True,
        )
        for candidate in ranked:
            if candidate.kind == "debug" and candidate.install_path is not None:
                siblings = [
                    item for item in ranked
                    if item.kind == "client" and item.install_path == candidate.install_path
                ]
                for sibling in siblings[:1]:
                    url = self.extract_from_candidate(sibling)
                    if url:
                        return url
            url = self.extract_from_candidate(candidate)
            if url:
                return url
        return None

    def discover(
        self,
        candidates: list[ConveneLogCandidate],
    ) -> ConveneCaptureContext | None:
        ranked = sorted(
            (item for item in candidates if item.path.is_file()),
            key=lambda item: item.path.stat().st_mtime,
            reverse=True,
        )
        for candidate in ranked:
            if candidate.kind == "debug" and candidate.install_path is not None:
                siblings = [
                    item for item in ranked
                    if item.kind == "client" and item.install_path == candidate.install_path
                ]
                for sibling in siblings[:1]:
                    url = self.extract_from_candidate(sibling)
                    if url:
                        return _capture_context_from_url(
                            url,
                            discovery_source="client_log",
                            log_path=sibling.path,
                            log_mtime=sibling.path.stat().st_mtime,
                        )
            url = self.extract_from_candidate(candidate)
            if url:
                return _capture_context_from_url(
                    url,
                    discovery_source=f"{candidate.kind}_log",
                    log_path=candidate.path,
                    log_mtime=candidate.path.stat().st_mtime,
                )
        return None


def _normalize_pull_record(
    record: dict[str, object],
    source: str = "convene_api",
    player_id: str | None = None,
) -> dict[str, object]:
    timestamp = record.get("timestamp", record.get("time", record.get("date")))
    name = record.get("name", record.get("item", record.get("title")))
    rarity = (
        record.get("rarity")
        if record.get("rarity") not in (None, "")
        else record.get("quality")
        if record.get("quality") not in (None, "")
        else record.get("rank")
        if record.get("rank") not in (None, "")
        else record.get("qualityLevel")
    )
    pool = record.get("pool", record.get("type", record.get("gacha_type")))
    if pool in (None, ""):
        pool = record.get("cardPoolType") or record_pool(record)
    official_id = next(
        (
            record.get(key)
            for key in ("seq_id", "seqId", "pull_id", "id")
            if record.get(key) not in (None, "")
        ),
        None,
    )
    normalized = {
        **record,
        "timestamp": timestamp,
        "pool": pool,
        "name": name,
        "rarity": rarity,
        "raw": dict(record),
        "source": source,
        "official_id": official_id,
    }
    if player_id is not None and player_id.strip():
        normalized["player_id"] = player_id.strip()
    if official_id not in (None, ""):
        normalized["dedup_key"] = f"id:{official_id}"
    elif all(value not in (None, "") for value in (timestamp, pool, name, rarity)):
        normalized["dedup_key"] = f"fields:{timestamp}|{pool}|{name}|{rarity}"
    else:
        normalized["dedup_key"] = None
        normalized["is_pull"] = False
    return normalized


@dataclass
class TrackerStatus:
    log_status: str = "unknown"
    api_status: str = "unknown"
    history_status: str = "unknown"
    sync_status: str = "idle"
    last_sync_at: str | None = None
    last_success_at: str | None = None
    history_age: float | None = None
    is_partial: bool | None = None
    is_stale: bool | None = None
    source: str = "unknown"
    capture_source: str = "unknown"
    is_new_capture: bool | None = None
    message: str = ""
    new_records_count: int = 0
    pool_status: dict[str, dict[str, object]] = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_age(records: list[dict[str, object]]) -> float | None:
    timestamps: list[datetime] = []
    for record in records:
        value = record.get("timestamp", record.get("time", record.get("date")))
        parsed = parse_convene_datetime(value)
        if parsed is not None:
            timestamps.append(parsed)
    if not timestamps:
        return None
    return max(0.0, (datetime.now(KURO_TIMEZONE) - max(timestamps)).total_seconds())


def _pool_results_are_partial(
    pool_statuses: dict[str, dict[str, object]],
) -> bool:
    successful = any(
        status.get("status") in {"success", "success_empty"}
        for status in pool_statuses.values()
    )
    incomplete = any(
        status.get("status") == "error"
        or not status.get("completed", False)
        for status in pool_statuses.values()
    )
    return successful and incomplete


def _all_pools_failed(
    pool_statuses: dict[str, dict[str, object]],
) -> bool:
    expected_pool_keys = {"1", "2", "3", "4"}
    if not expected_pool_keys.issubset(pool_statuses):
        return False
    return all(
        pool_statuses[pool_key].get("status") == "error"
        and pool_statuses[pool_key].get("completed") is True
        for pool_key in expected_pool_keys
    )


def _status_message_with_pool_details(
    message: str,
    pool_statuses: dict[str, dict[str, object]],
) -> str:
    debug_lines: list[str] = [
        "[DEBUG pool_statuses] " + ("is_none=True" if pool_statuses is None else f"count={len(pool_statuses) if isinstance(pool_statuses, dict) else 'non_dict'}")
    ]
    if isinstance(pool_statuses, dict):
        for pool_key in sorted(pool_statuses, key=lambda value: int(value) if str(value).isdigit() else 999):
            pool_status = pool_statuses.get(pool_key)
            if not isinstance(pool_status, dict):
                debug_lines.append(f"P{pool_key} status=non_dict")
                continue
            detail = pool_status.get("detail")
            status_name = str(pool_status.get("status") or "unknown")
            has_detail = bool(detail)
            detail_text = str(detail) if has_detail else ""
            debug_lines.append(
                f"P{pool_key} status={status_name} record_count={pool_status.get('record_count', 'n/a')} detail={str(has_detail).lower()}"
                + (f" detail_value={detail_text[:120]}" if has_detail else "")
            )
    debug_prefix = " | ".join(debug_lines[:8])
    if not pool_statuses:
        return f"{message} | {debug_prefix}" if message else debug_prefix
    details: list[str] = []
    for pool_key in sorted(pool_statuses, key=lambda value: int(value) if str(value).isdigit() else 999):
        pool_status = pool_statuses.get(pool_key)
        if not isinstance(pool_status, dict):
            continue
        detail = str(pool_status.get("detail") or pool_status.get("message") or "").strip()
        status_name = str(pool_status.get("status") or "unknown")
        if not detail and status_name:
            detail = status_name
        if detail:
            details.append(f"P{pool_key}: {detail[:90]}" + ("..." if len(detail) > 90 else ""))
    if not details:
        return f"{message} | {debug_prefix}" if message else debug_prefix
    suffix = " | ".join(details[:3])
    if message:
        return f"{message} | {suffix} | {debug_prefix}"
    return f"{suffix} | {debug_prefix}"


def _failed_tracker_status(
    pool_statuses: dict[str, dict[str, object]],
    sync_status: str,
    message: str,
    _started_at: str,
) -> TrackerStatus:
    return TrackerStatus(
        api_status=sync_status,
        history_status="unchanged",
        sync_status=sync_status,
        last_sync_at=_utc_now_iso(),
        is_partial=_pool_results_are_partial(pool_statuses),
        source="api",
        message=_status_message_with_pool_details(message, pool_statuses),
        pool_status=dict(pool_statuses),
    )


def extract_convene_parameters(url: str) -> tuple[str, str]:
    """Extract the player and record IDs used by the Convene API request."""
    context = extract_convene_request_context(url)
    return str(context["player_id"]), str(context["record_id"])


def extract_convene_request_context(url: str) -> dict[str, str | int]:
    """Extract the request context used by the current Convene browser API."""
    clean_url = unquote(url.replace("\r", "").replace("\n", "").strip())
    player_match = CONVENE_PLAYER_ID_RE.search(clean_url)
    record_match = CONVENE_RECORD_ID_RE.search(clean_url)
    server_match = CONVENE_SERVER_ID_RE.search(clean_url)
    card_pool_match = CONVENE_CARD_POOL_ID_RE.search(clean_url)
    language_match = CONVENE_LANGUAGE_CODE_RE.search(clean_url)

    player_id = player_match.group(1) if player_match else ""
    record_id = record_match.group(1) if record_match else ""
    server_id = server_match.group(1) if server_match else ""
    card_pool_id = card_pool_match.group(1) if card_pool_match else ""
    language_code = language_match.group(1) if language_match else "en"

    if not player_id or not record_id:
        raise ValueError("A Convene Record URL não contém player_id e record_id.")
    if not server_id:
        raise ValueError("A Convene Record URL não contém svr_id.")
    if not card_pool_id:
        raise ValueError("A Convene Record URL não contém resources_id.")

    return {
        "player_id": player_id,
        "record_id": record_id,
        "server_id": server_id,
        "card_pool_id": card_pool_id,
        "language_code": language_code,
        "card_pool_type": 1,
    }


def _capture_context_from_url(
    url: str,
    *,
    discovery_source: str,
    log_path: Path | None = None,
    log_mtime: float | None = None,
) -> ConveneCaptureContext:
    request_context = extract_convene_request_context(url)
    return ConveneCaptureContext(
        source_url=url,
        player_id=str(request_context["player_id"]),
        record_id=str(request_context["record_id"]),
        svr_id=str(request_context["server_id"]),
        resources_id=str(request_context["card_pool_id"]),
        lang=str(request_context["language_code"]),
        log_path=log_path,
        log_mtime=log_mtime,
        discovered_at=_utc_now_iso(),
        discovery_source=discovery_source,
    )


def capture_from_changed_clipboard(
    previous_text: str,
    current_text: str,
) -> ConveneCaptureContext | None:
    """Accept an external URL only when the clipboard changed and is valid."""
    normalized_previous = previous_text.replace("\r", "").replace("\n", "").strip()
    normalized_current = current_text.replace("\r", "").replace("\n", "").strip()
    if not normalized_current or normalized_current == normalized_previous:
        return None
    try:
        return _capture_context_from_url(
            normalized_current,
            discovery_source="external_clipboard",
        )
    except ValueError:
        return None


def build_convene_url_from_context(context: dict[str, object] | None) -> str | None:
    """Rebuild the active Convene URL from a previously saved request context."""
    if not isinstance(context, dict):
        return None
    player_id = str(context.get("player_id") or "").strip()
    record_id = str(context.get("record_id") or "").strip()
    server_id = str(context.get("server_id") or "").strip()
    card_pool_id = str(context.get("card_pool_id") or "").strip()
    language_code = str(context.get("language_code") or "en").strip() or "en"
    if not all((player_id, record_id, server_id, card_pool_id)):
        return None
    card_pool_type = context.get("card_pool_type", 1)
    try:
        if isinstance(card_pool_type, bool) or not isinstance(
            card_pool_type, (str, int, float)
        ):
            raise ValueError("Tipo de pool inválido")
        card_pool_type_value = int(card_pool_type)
    except (TypeError, ValueError):
        card_pool_type_value = 1
    return (
        "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html#/record?"
        f"svr_id={server_id}&player_id={player_id}&lang={language_code}&gacha_id=100081&"
        f"gacha_type={card_pool_type_value}&svr_area=global&record_id={record_id}&"
        f"resources_id={card_pool_id}&platform=PC"
    )


def fetch_convene_records(
    convene_url: str,
    *,
    pool_statuses: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Fetch records for every known banner pool using the active browser API."""
    request_context = extract_convene_request_context(convene_url)
    player_id = request_context["player_id"]
    record_id = request_context["record_id"]
    server_id = request_context["server_id"]
    card_pool_id = request_context["card_pool_id"]
    language_code = request_context["language_code"]

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": language_code or "en",
        "Content-Type": "application/json",
        "Origin": "https://aki-gm-resources-oversea.aki-game.net",
        "Referer": "https://aki-gm-resources-oversea.aki-game.net/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
    }
    records: list[dict[str, object]] = []
    context_payload: dict[str, object] = {
        "player_id": player_id,
        "record_id": record_id,
        "server_id": server_id,
        "card_pool_id": card_pool_id,
        "language_code": language_code,
        "card_pool_type": 1,
    }
    pool_names = {
        1: "resonator",
        2: "weapon",
        3: "standard_character",
        4: "standard_weapon",
    }
    connection_errors: list[requests.exceptions.ConnectionError] = []
    context_saved = False

    for pool_type, pool_name in pool_names.items():
        pool_key = str(pool_type)
        if pool_statuses is not None:
            pool_statuses[pool_key] = {
                "status": "started",
                "completed": False,
                "record_count": 0,
                "detail": f"[Convene] pool={pool_type} status=started",
            }

        payload = {
            "playerId": player_id,
            "cardPoolId": card_pool_id,
            "cardPoolType": pool_type,
            "languageCode": language_code,
            "recordId": record_id,
            "serverId": server_id,
        }

        print(
            "[CONVENE REQUEST] "
            f"endpoint={KURO_RECORD_API_URL} "
            "payload="
            f"playerId={player_id} cardPoolId={card_pool_id} "
            f"cardPoolType={payload['cardPoolType']} "
            f"languageCode={language_code} recordId={record_id} serverId={server_id}"
        )
        try:
            response = requests.post(
                KURO_RECORD_API_URL,
                json=payload,
                headers=headers,
                timeout=15,
            )
        except requests.exceptions.Timeout as error:
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": f"Tempo limite da API: {error}",
                    "detail": f"[Convene] pool={pool_type} status=timeout",
                })
            continue
        except requests.exceptions.ConnectionError as error:
            connection_errors.append(error)
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": CONVENE_DNS_ERROR_MESSAGE,
                    "detail": f"[Convene] pool={pool_type} status=dns_error message=" + CONVENE_DNS_ERROR_MESSAGE[:90],
                })
            continue

        status_code = response.status_code
        if status_code != 200:
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": f"Erro HTTP {status_code}",
                    "detail": f"[Convene] pool={pool_type} status={status_code} message=HTTP_{status_code}",
                })
            continue

        try:
            parsed = response.json()
        except ValueError:
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": "Resposta da API não é JSON válido.",
                    "detail": f"[Convene] pool={pool_type} status={status_code} json=invalid",
                })
            continue

        if not isinstance(parsed, dict):
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": "Resposta da API inválida.",
                    "detail": f"[Convene] pool={pool_type} status={status_code} json=invalid type={type(parsed).__name__}",
                })
            continue

        json_code = parsed.get("code", "n/a")
        api_message = parsed.get("message") or parsed.get("msg") or ""
        data_value = parsed.get("data")
        newest_time: object = ""
        oldest_time: object = ""
        if isinstance(data_value, list):
            newest_record = None
            oldest_record = None
            for item in data_value:
                if not isinstance(item, dict):
                    continue
                item_time = str(item.get("time", item.get("timestamp", item.get("date", ""))) or "")
                if newest_record is None or item_time >= str(newest_record.get("time", newest_record.get("timestamp", newest_record.get("date", ""))) or ""):
                    newest_record = item
                if oldest_record is None or item_time <= str(oldest_record.get("time", oldest_record.get("timestamp", oldest_record.get("date", ""))) or ""):
                    oldest_record = item
            newest_time = newest_record.get("time", newest_record.get("timestamp", newest_record.get("date", ""))) if isinstance(newest_record, dict) else ""
            oldest_time = oldest_record.get("time", oldest_record.get("timestamp", oldest_record.get("date", ""))) if isinstance(oldest_record, dict) else ""
            newest_name = newest_record.get("name", newest_record.get("item", newest_record.get("title", ""))) if isinstance(newest_record, dict) else ""
            oldest_name = oldest_record.get("name", oldest_record.get("item", oldest_record.get("title", ""))) if isinstance(oldest_record, dict) else ""
            print(
                "[CONVENE RESPONSE] "
                f"status={status_code} code={json_code} message={api_message!a} "
                f"data_count={len(data_value)} newest_time={newest_time!a} newest_name={newest_name!a} "
                f"oldest_time={oldest_time!a} oldest_name={oldest_name!a} record_id={record_id}"
            )

        if json_code not in (0, "0"):
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": api_message or "Resposta da API inválida.",
                    "detail": f"[Convene] pool={pool_type} status={status_code} code={json_code} message={api_message[:80] if api_message else 'n/a'}",
                })
            continue

        if not isinstance(data_value, list):
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": "Estrutura da API inesperada.",
                    "detail": f"[Convene] pool={pool_type} status={status_code} code={json_code} data_type={type(data_value).__name__}",
                })
            continue

        if not context_saved:
            try:
                ConveneStorageManager().save_context(context_payload)
                context_saved = True
                print(
                    "[Convene] Persisted matching context. "
                    f"record_id={record_id} count={len(data_value)} oldest={oldest_time if oldest_time else 'n/a'} newest={newest_time if newest_time else 'n/a'}"
                )
            except Exception as error:  # pragma: no cover - diagnostic-only persistence guard
                print(f"[Convene] Failed to persist context: {error}")

        pool_records = extract_records(data_value)
        tagged_records = []
        for record in pool_records:
            tagged_record = dict(record)
            tagged_record["pool"] = pool_name
            tagged_records.append(tagged_record)
        records.extend(tagged_records)
        if pool_statuses is not None:
            detail_message = api_message[:80] if api_message else "success"
            pool_statuses[pool_key].update({
                "status": "success" if tagged_records else "success_empty",
                "completed": True,
                "record_count": len(tagged_records),
                "message": detail_message,
                "detail": f"[Convene] pool={pool_type} status={status_code} code={json_code} message={detail_message} data_count={len(tagged_records)}",
            })

    if not records and len(connection_errors) == len(pool_names):
        raise requests.exceptions.ConnectionError(CONVENE_DNS_ERROR_MESSAGE)
    return records


def get_brave_cdp_convene_url(timeout: float = 2.0) -> str | None:
    """Probe the active Brave debug session for the current Convene Record URL."""
    try:
        response = requests.get(BRAVE_CDP_URL, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        pages = response.json()
    except ValueError:
        return None
    if not isinstance(pages, list):
        return None
    for page in reversed(pages):
        if not isinstance(page, dict):
            continue
        url = str(page.get("url") or "").strip()
        if not url:
            continue
        lowered = url.lower()
        if "aki-gm-resources" in lowered and "/record" in lowered:
            return url
    return None


def get_convene_url_from_log(log_path: str | Path | None = None) -> str:
    """Return a URL found in current logs, never from restored context."""
    return ClientLogReader(log_path).get_capture_context().source_url


class ClientLogReader:
    """Native reader for Wuthering Waves logs and Convene URLs."""

    def __init__(self, log_path: str | Path | None = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else None

    def get_capture_context(self) -> ConveneCaptureContext:
        candidates = ConveneLogLocator(self.log_path).locate()
        if not candidates:
            raise FileNotFoundError(CONVENE_URL_NOT_FOUND_MESSAGE)
        capture = ConveneUrlExtractor().discover(candidates)
        if capture is None:
            raise ValueError(CONVENE_URL_NOT_FOUND_MESSAGE)
        return capture

    def get_convene_url(self) -> str:
        return self.get_capture_context().source_url


class HorizontalPageStack(QFrame):
    """Fixed horizontal page strip used by the luck assessment panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages: list[QWidget] = []
        self._current_index = 0
        self._strip = QWidget(self)
        self._layout = QHBoxLayout(self._strip)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._animation: QPropertyAnimation | None = None

    def addWidget(self, widget: QWidget) -> None:
        widget.setParent(self._strip)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pages.append(widget)
        self._layout.addWidget(widget)
        self._sync_geometry()

    def count(self) -> int:
        return len(self._pages)

    def currentIndex(self) -> int:
        return self._current_index

    def slide_to(self, index: int, direction: int) -> None:
        if index == self._current_index or not self._pages:
            return
        width = max(1, self.width())
        start = QPoint(-self._current_index * width, 0)
        end = QPoint(-index * width, 0)
        self._strip.move(start)
        animation = QPropertyAnimation(self._strip, b"pos", self)
        animation.setDuration(250)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)

        def finish() -> None:
            self._current_index = index
            self._strip.move(end)
            self._animation = None

        animation.finished.connect(finish)
        self._animation = animation
        animation.start()

    def is_animating(self) -> bool:
        return self._animation is not None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_geometry()

    def _sync_geometry(self) -> None:
        width = max(1, self.width())
        self._strip.setGeometry(
            -self._current_index * width,
            0,
            width * max(1, len(self._pages)),
            max(1, self.height()),
        )


class PityHistoryImportWorker(QObject):
    imported = Signal(object)
    failed = Signal(str)
    status = Signal(object)

    def __init__(self, history_url: str) -> None:
        super().__init__()
        self.history_url = history_url.strip()

    @Slot()
    def run(self) -> None:
        pool_statuses: dict[str, dict[str, object]] = {}
        started_at = _utc_now_iso()
        self.status.emit(TrackerStatus(
            api_status="started",
            sync_status="running",
            last_sync_at=None,
            source="api",
            pool_status=pool_statuses,
        ))
        try:
            request_context = extract_convene_request_context(self.history_url)
            player_id = str(request_context["player_id"]).strip()
            if not player_id:
                raise ValueError("A valid player_id is required for Convene synchronization.")
            history_storage = ConveneStorageManager()
            previous_context = history_storage.load_context()
            previous_context_player_id = (
                str(previous_context["player_id"])
                if previous_context is not None
                else None
            )
            raw_records = fetch_convene_records(
                self.history_url,
                pool_statuses=pool_statuses,
            )
            if _all_pools_failed(pool_statuses):
                message = "Falha ao consultar todos os pools de Convene."
                self.status.emit(_failed_tracker_status(
                    pool_statuses,
                    "error",
                    message,
                    started_at,
                ))
                self.failed.emit(message)
                return
            extracted_records = [record for record in raw_records if isinstance(record, dict)]
            normalized_records = [
                _normalize_pull_record(record, player_id=player_id)
                for record in extracted_records
            ]
            now = datetime.now(KURO_TIMEZONE)
            month_start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if now.month == 12:
                next_month = now.replace(
                    year=now.year + 1,
                    month=1,
                    day=1,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            else:
                next_month = now.replace(
                    month=now.month + 1,
                    day=1,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            def is_current_month_record(record: dict[str, object]) -> bool:
                parsed = parse_convene_datetime(record.get("timestamp"))
                if parsed is None:
                    return False
                return month_start <= parsed < next_month

            current_month_records = [
                record for record in normalized_records
                if is_current_month_record(record)
            ]
            persistable_records = [
                record for record in current_month_records
                if record.get("is_pull", True)
            ]
            partial = _pool_results_are_partial(pool_statuses)
            finished_at = _utc_now_iso()
            if persistable_records:
                try:
                    history, new_records_count = history_storage.merge_active_player_with_metadata(
                        persistable_records,
                        player_id,
                        previous_context_player_id=previous_context_player_id,
                    )
                    non_pull_records = [
                        record for record in current_month_records
                        if not record.get("is_pull", True)
                    ]
                    self.status.emit(TrackerStatus(
                        api_status="partial" if partial else "success",
                        history_status="updated" if new_records_count else "unchanged",
                        sync_status=(
                            "partial" if partial
                            else "success_no_new" if not new_records_count
                            else "success"
                        ),
                        last_sync_at=finished_at,
                        last_success_at=None if partial else finished_at,
                        history_age=_history_age(history),
                        is_partial=partial,
                        is_stale=None,
                        source="api",
                        message=_status_message_with_pool_details(
                            "Sincronização parcial" if partial else "Sincronização concluída",
                            pool_statuses,
                        ),
                        new_records_count=new_records_count,
                        pool_status=dict(pool_statuses),
                    ))
                    self.imported.emit([*history, *non_pull_records])
                except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                    print(f"[Convene] Falha ao persistir histórico: {error}")
                    self.status.emit(TrackerStatus(
                        api_status="success",
                        history_status="error",
                        sync_status="error",
                        last_sync_at=finished_at,
                        is_partial=partial,
                        source="api",
                        message=f"Falha ao persistir histórico: {error}",
                        pool_status=dict(pool_statuses),
                    ))
                    existing_history = ConveneStorageManager().load_for_player(player_id)
                    self.imported.emit([*existing_history, *current_month_records])
            else:
                self.status.emit(TrackerStatus(
                    api_status="partial" if partial else "success_empty",
                    history_status="unchanged",
                    sync_status="partial" if partial else "success_no_new",
                    last_sync_at=finished_at,
                    last_success_at=None if partial else finished_at,
                    history_age=None,
                    is_partial=partial,
                    source="api",
                    message=_status_message_with_pool_details(
                        "Sincronização parcial" if partial else "Nenhuma pull normalizada retornada",
                        pool_statuses,
                    ),
                    pool_status=dict(pool_statuses),
                ))
                existing_history = ConveneStorageManager().load_for_player(player_id)
                self.imported.emit([*existing_history, *current_month_records])
        except requests.exceptions.ConnectionError:
            message = CONVENE_DNS_ERROR_MESSAGE
            print(f"[Convene] {message}")
            self.status.emit(_failed_tracker_status(
                pool_statuses,
                "offline",
                message,
                started_at,
            ))
            self.failed.emit(message)
        except requests.RequestException as error:
            message = f"Falha de rede ao consultar a API de gacha: {error}"
            print(f"[Convene] {message}")
            self.status.emit(_failed_tracker_status(
                pool_statuses,
                "error",
                message,
                started_at,
            ))
            self.failed.emit(message)
        except Exception as error:
            message = f"Falha na consulta do Client.log: {error}"
            print(f"[Convene] {message}")
            self.status.emit(_failed_tracker_status(
                pool_statuses,
                "error",
                message,
                started_at,
            ))
            self.failed.emit(message)

    @staticmethod
    def _extract_records(data: object) -> list[dict[str, object]]:
        return extract_records(data)


class PityTrackerWorker(QObject):
    """Qt worker endpoint for an authorized local history adapter."""

    new_pull_captured = Signal(list)
    shot_captured = Signal(dict)

    @Slot(list)
    def ingest_items(self, items: list[object]) -> None:
        if items:
            self.new_pull_captured.emit(items)
            self.shot_captured.emit({"items": items})


class _BannerArtLabel(QLabel):
    """Banner art clipped to a soft, semi-rounded rectangle."""

    CORNER_RADIUS = 14

    def __init__(
        self,
        parent: QWidget | None = None,
        backdrop: str = "#111521",
        fit_entire: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setScaledContents(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._source = QPixmap()
        self._backdrop = QColor(backdrop)
        self._fit_entire = fit_entire

    def set_backdrop(self, color: str) -> None:
        self._backdrop = QColor(color)
        self.update()

    def set_art(self, pixmap: QPixmap) -> None:
        self._source = pixmap
        self.update()

    def resizeEvent(self, event) -> None:
        mask = QPixmap(self.size())
        mask.fill(Qt.GlobalColor.transparent)
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.CORNER_RADIUS, self.CORNER_RADIUS)
        painter.fillPath(path, Qt.GlobalColor.white)
        painter.end()
        self.setMask(
            mask.createMaskFromColor(
                QColor(Qt.GlobalColor.transparent),
                Qt.MaskMode.MaskInColor,
            )
        )
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._source.isNull() or self.width() <= 0 or self.height() <= 0:
            painter.end()
            return

        mode = (
            Qt.AspectRatioMode.KeepAspectRatio
            if self._fit_entire
            else Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )
        scaled = self._source.scaled(
            self.size(), mode, Qt.TransformationMode.SmoothTransformation
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        image_rect = QRectF(x, y, scaled.width(), scaled.height()).adjusted(
            0.5, 0.5, -0.5, -0.5
        )
        path = QPainterPath()
        path.addRoundedRect(image_rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        painter.setClipPath(path)
        painter.fillRect(image_rect, self._backdrop)
        painter.drawPixmap(x, y, scaled)
        painter.end()


class _ConveneBannerCard(QFrame):
    """Compact tracker row with a clipped banner thumbnail."""

    def __init__(
        self,
        title: str,
        accent: str,
        fit_entire: bool = False,
        art_size: tuple[int, int] = (64, 64),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("conveneBannerCard")
        self.setMinimumHeight(78)
        self.setMaximumHeight(86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)
        backdrop = (
            "#2A1945" if accent == "#A855F7"
            else "#302817" if accent == "#EAB308"
            else "#111521"
        )
        self.art = _BannerArtLabel(self, backdrop, fit_entire)
        self.art.setFixedSize(*art_size)
        shadow = QGraphicsDropShadowEffect(self.art)
        shadow.setBlurRadius(10)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 145))
        self.art.setGraphicsEffect(shadow)
        layout.addWidget(self.art)

        self.overlay = QFrame(self)
        self.overlay.setObjectName("conveneBannerOverlay")
        self.overlay.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(1)
        parts = title.split(" - ", 1)
        category = parts[1] if len(parts) == 2 else title
        name = parts[0] if len(parts) == 2 else "Standard Convene"
        self.category_label = QLabel(category, self.overlay)
        self.category_label.setObjectName("conveneBannerCategory")
        self.category_label.setStyleSheet(f"color: {accent};")
        overlay_layout.addWidget(self.category_label)
        self.title_label = QLabel(name, self.overlay)
        self.title_label.setObjectName("conveneBannerTitle")
        overlay_layout.addWidget(self.title_label)
        self.pity_label = QLabel("-- / 80", self.overlay)
        self.pity_label.setObjectName("conveneBannerPity")
        overlay_layout.addWidget(self.pity_label)
        overlay_layout.addStretch(1)
        self.badge = QLabel(self.overlay)
        self.badge.setObjectName("conveneBannerBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setMinimumWidth(66)
        self.badge.setMaximumWidth(120)
        overlay_layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.overlay, 1)

    def set_pity(self, value: int | None) -> None:
        display = value if value is not None else "--"
        self.pity_label.setText(f"{display} / 80")

    def set_badges(self, values: list[str]) -> None:
        self.badge.setText(values[0] if values else "")


class LegacyPityTrackerWidget(QFrame):
    """Glassmorphism tracker. Feed authorized pull data through capture_pull."""

    new_pull_captured = Signal(list)
    state_changed = Signal(object)
    status_changed = Signal(object)
    history_changed = Signal(list)
    sync_log_clicked = Signal()
    view_history_clicked = Signal()
    export_data_clicked = Signal()

    def __init__(
        self,
        active_character: str = "qingxiao",
        banner_images: dict[str, object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pityTracker")
        self.setMinimumWidth(320)
        self.setMaximumWidth(360)
        self.setFixedHeight(440)
        self.setMaximumHeight(480)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.state = PityState()
        self.active_character = active_character.casefold().strip()
        self.banner_images = banner_images or {}
        self.image_network = QNetworkAccessManager(self)
        self._image_replies: dict[str, QNetworkReply] = {}
        self._import_thread = None
        self._import_worker = None
        self._pwsh_process: subprocess.Popen | None = None
        self._clipboard_before_external = ""
        self.last_capture_context: ConveneCaptureContext | None = None
        self._pwsh_poll_timer = QTimer(self)
        self._pwsh_poll_timer.setInterval(250)
        self._pwsh_poll_timer.timeout.connect(self._await_wuwatracker_import)
        self.tracker_status = TrackerStatus()
        storage = ConveneStorageManager()
        saved_context = storage.load_context()
        saved_player_id = (
            str(saved_context.get("player_id") or "").strip()
            if saved_context is not None
            else ""
        )
        self.active_player_id: str | None = saved_player_id or None
        self.history_records: list[dict[str, object]] = (
            storage.load_for_player(saved_player_id)
            if saved_player_id
            else []
        )
        self._update_state_from_records(self.history_records)
        self._pulse_value = 0.0
        self._palette_accent = "#A855F7"
        self._build_large_banner_ui()
        tracker_shadow = QGraphicsDropShadowEffect(self)
        tracker_shadow.setBlurRadius(24)
        tracker_shadow.setOffset(0, 6)
        tracker_shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(tracker_shadow)
        self.apply_wallpaper_palette(*wallpaper_palette())
        self._load_visual_assets()
        self._pulse_animation = QPropertyAnimation(self, b"pulseValue", self)
        self._pulse_animation.setDuration(420)
        self._pulse_animation.setStartValue(1.0)
        self._pulse_animation.setEndValue(0.0)
        self._pulse_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def refresh_convene_context_from_log(self) -> None:
        """Restore the visible partition from a discovered URL without persisting it."""
        try:
            capture = ClientLogReader().get_capture_context()
            self._activate_player_history(capture.player_id)
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return

    def _activate_player_history(self, player_id: str) -> None:
        normalized_player_id = player_id.strip()
        if not normalized_player_id:
            return
        try:
            records = ConveneStorageManager().load_for_player(normalized_player_id)
        except ValueError:
            return
        self.active_player_id = normalized_player_id
        self.history_records = records
        self._update_state_from_records(self.history_records)
        self._refresh_labels()
        self.state_changed.emit(self.state)
        self.history_changed.emit(self.history_records)

    def _build_large_banner_ui(self) -> None:
        self.setStyleSheet(
            "QFrame#pityTracker { background-color: rgba(18, 22, 30, 224); "
            "border: 1px solid rgba(80, 160, 240, 64); border-radius: 16px; }"
            "QFrame#pitySection { background: rgba(18, 22, 30, 155); "
            "border: 1px solid rgba(255, 255, 255, 25); border-radius: 10px; }"
            "QFrame#conveneBannerCard { background-color: rgba(12, 15, 22, 166); "
            "border: 1px solid rgba(255, 255, 255, 20); border-radius: 10px; }"
            "QLabel#conveneBannerCategory { color: #73D7F2; font-size: 9px; font-weight: 800; }"
            "QLabel#conveneBannerTitle { color: #FFFFFF; font-size: 13px; font-weight: 800; }"
            "QLabel#conveneBannerPity { color: #73D7F2; font-size: 18px; font-weight: 800; }"
            "QLabel#conveneBannerBadge { color: #D7F6FF; background: rgba(12, 28, 42, 150); "
            "border: 1px solid rgba(80, 190, 235, 100); border-radius: 10px; padding: 3px 8px; "
            "font-size: 9px; font-weight: 700; }"
            "QLabel#pityHeader { color: #F5F7FA; font-size: 12px; font-weight: 900; letter-spacing: 1px; }"
            "QLabel#pityOnline { color: #6FE0B0; font-size: 9px; font-weight: 800; }"
            "QLabel#pityMeta { color: #AAB6C4; font-size: 9px; }"
            "QLabel#pityStatIcon { color: #B9D8E6; font-size: 17px; }"
            "QLabel#pityStatValue { color: #D6E8F0; font-size: 10px; font-weight: 700; }"
            "QLabel#pitySectionTitle { color: #F4F7FF; font-size: 11px; font-weight: 900; }"
            "QLabel#pityStatusTag { color: #6FE0B0; background: rgba(35, 150, 105, 45); "
            "border: 1px solid rgba(111, 224, 176, 100); border-radius: 8px; padding: 3px 7px; font-size: 8px; font-weight: 800; }"
            "QLabel#pityLuckValue { color: #FFD76A; font-size: 18px; font-weight: 900; }"
            "QLabel#pitySummaryValue { color: #F4F7FF; font-size: 16px; font-weight: 900; }"
            "QLabel#pitySummaryLabel { color: #AAB6C4; font-size: 8px; }"
            "QPushButton#pityIconButton { color: #D9EEF5; background: transparent; border: 0; "
            "font-size: 19px; padding: 0; }"
            "QPushButton#pitySyncButton { color: #E5F7FC; background: rgba(9, 35, 52, 210); "
            "border: 1px solid rgba(80, 190, 235, 120); border-radius: 7px; padding: 6px 8px; font-size: 8px; font-weight: 800; }"
            "QPushButton#pitySyncButton:hover { background: rgba(28, 75, 98, 210); border-color: #73E5FF; }"
            "QPushButton#pityIconButton:hover { color: #73E5FF; }"
            "QPushButton#pityFooter { color: #E5F7FC; background: rgba(12, 28, 42, 170); "
            "border: 1px solid rgba(80, 190, 235, 110); border-radius: 16px; padding: 7px 12px; "
            "font-size: 10px; font-weight: 800; }"
            "QPushButton#pityFooter:hover { background: rgba(28, 75, 98, 190); border-color: #73E5FF; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(5)
        tracker_badge = QLabel("CONVENE TRACKER")
        tracker_badge.setObjectName("pityHeader")
        header.addWidget(tracker_badge)
        online = QLabel("● ONLINE")
        online.setObjectName("pityOnline")
        header.addWidget(online)
        header.addStretch(1)
        history_button = QPushButton("•••")
        history_button.setObjectName("pityIconButton")
        history_button.setFixedSize(24, 24)
        history_button.setToolTip("Histórico completo")
        history_button.clicked.connect(self.view_history_clicked)
        header.addWidget(history_button)
        root.addLayout(header)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("pityScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.scroll_content = content
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 0)
        content_layout.setSpacing(8)

        sync_section = QFrame()
        sync_section.setObjectName("pitySection")
        sync_layout = QVBoxLayout(sync_section)
        sync_layout.setContentsMargins(9, 8, 9, 8)
        sync_layout.setSpacing(6)
        sync_heading = QHBoxLayout()
        sync_title = QLabel("Sincronização de dados")
        sync_title.setObjectName("pitySectionTitle")
        sync_heading.addWidget(sync_title)
        sync_heading.addStretch(1)
        self.sync_status = QLabel("Concluído / Sincronizado")
        self.sync_status.setObjectName("pityStatusTag")
        sync_heading.addWidget(self.sync_status)
        sync_layout.addLayout(sync_heading)
        self.sync_button = QPushButton("Sincronizar Client.log")
        self.sync_button.setObjectName("pitySyncButton")
        self.sync_button.clicked.connect(self._request_sync)
        sync_layout.addWidget(self.sync_button)
        self.sync_label = QLabel("Última sincronização: --")
        self.sync_label.setObjectName("pityMeta")
        sync_layout.addWidget(self.sync_label)
        content_layout.addWidget(sync_section)

        banners_title = QLabel("Banners em destaque")
        banners_title.setObjectName("pitySectionTitle")
        content_layout.addWidget(banners_title)
        character_name = self.active_character.replace(" xuanling", "").title()
        self.resonator_card = _ConveneBannerCard(
            f"{character_name} - Event Resonator", "#A855F7"
        )
        self.resonator_value = self.resonator_card.pity_label
        self.resonator_progress = self._make_progress()
        self.guarantee_label = QLabel(self.resonator_card.overlay)
        self.weapon_card = _ConveneBannerCard(
            "Thousandfold Deliverance - Signature Weapon",
            "#EAB308",
            True,
            (64, 64),
        )
        self.weapon_value = self.weapon_card.pity_label
        self.weapon_progress = self._make_progress()
        self.standard_card = _ConveneBannerCard("Standard Convene", "#38BDF8")
        self.standard_character = self.standard_card.pity_label
        self.standard_weapon = QLabel()
        self.reverberation_card = _ConveneBannerCard(
            "Standard Convene - Invocação de Reverberação", "#A855F7"
        )
        self.reverberation_weapon_card = _ConveneBannerCard(
            "Standard Convene - Arma de Reverberação", "#EAB308", True
        )

        for card in (
            self.resonator_card,
            self.weapon_card,
            self.reverberation_card,
            self.reverberation_weapon_card,
        ):
            content_layout.addWidget(card)

        summary_section = QFrame()
        summary_section.setObjectName("pitySection")
        summary_layout = QVBoxLayout(summary_section)
        summary_layout.setContentsMargins(9, 8, 9, 8)
        summary_title = QLabel("Ressonantes em Destaque")
        summary_title.setObjectName("pitySectionTitle")
        summary_layout.addWidget(summary_title)
        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(12)
        summary_grid.setVerticalSpacing(8)
        self.summary_values: dict[str, QLabel] = {}
        for index, (key, label) in enumerate((
            ("pulls", "Total de Giros"),
            ("astrites", "Total de Astrites"),
            ("five", "5★ Giros"),
            ("four", "4★ Giros"),
        )):
            cell = QVBoxLayout()
            value_label = QLabel("--")
            value_label.setObjectName("pitySummaryValue")
            label_widget = QLabel(label)
            label_widget.setObjectName("pitySummaryLabel")
            cell.addWidget(value_label)
            cell.addWidget(label_widget)
            self.summary_values[key] = value_label
            summary_grid.addLayout(cell, index // 2, index % 2)
        summary_layout.addLayout(summary_grid)
        content_layout.addWidget(summary_section)

        luck_section = QFrame()
        luck_section.setObjectName("pitySection")
        luck_layout = QVBoxLayout(luck_section)
        luck_layout.setContentsMargins(9, 8, 9, 8)
        luck_heading = QHBoxLayout()
        luck_title = QLabel("Avaliação de Sorte")
        luck_title.setObjectName("pitySectionTitle")
        luck_heading.addWidget(luck_title)
        luck_heading.addStretch(1)
        previous_button = QPushButton("<")
        previous_button.setObjectName("pityIconButton")
        previous_button.setFixedSize(24, 24)
        next_button = QPushButton(">")
        next_button.setObjectName("pityIconButton")
        next_button.setFixedSize(24, 24)
        luck_heading.addWidget(previous_button)
        luck_heading.addWidget(next_button)
        luck_layout.addLayout(luck_heading)
        self.luck_stack = HorizontalPageStack()
        self.luck_stack.setObjectName("pityLuckStack")
        self.luck_pages: dict[str, dict[str, QLabel]] = {}
        for key, title, obtained in (
            ("five", "Sorte 5★", "5★ obtidos: 0"),
            ("four", "Sorte 4★", "4★ obtidos: 0"),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(2)
            luck_value = QLabel(title)
            luck_value.setObjectName("pityLuckValue")
            average_label = QLabel("Pity médio: --")
            average_label.setObjectName("pityMeta")
            obtained_label = QLabel(obtained)
            obtained_label.setObjectName("pityMeta")
            message_label = QLabel("Faça mais giros para desbloquear")
            message_label.setObjectName("pityMeta")
            page_layout.addWidget(luck_value)
            page_layout.addWidget(average_label)
            page_layout.addWidget(obtained_label)
            page_layout.addWidget(message_label)
            self.luck_pages[key] = {
                "value": luck_value,
                "average": average_label,
                "obtained": obtained_label,
                "message": message_label,
            }
            self.luck_stack.addWidget(page)
        previous_button.clicked.connect(lambda: self._change_luck_page(-1))
        next_button.clicked.connect(lambda: self._change_luck_page(1))
        luck_layout.addWidget(self.luck_stack)
        content_layout.addWidget(luck_section)

        self.history_row = QHBoxLayout()
        self.footer_stats = QLabel()
        self.footer_stats.hide()
        self.last_update_value = QLabel("--")
        self.total_pulls_value = QLabel("--")
        self.next_pity_value = QLabel("--")
        footer_button = QPushButton("Ver Histórico Completo  >")
        footer_button.setObjectName("pityFooter")
        footer_button.clicked.connect(self.view_history_clicked)
        content_layout.addWidget(footer_button)
        content_layout.addStretch(1)
        self.scroll_area.setWidget(content)
        root.addWidget(self.scroll_area, 1)
        self._refresh_labels()

    def _change_luck_page(self, direction: int) -> None:
        current_index = self.luck_stack.currentIndex()
        next_index = max(0, min(self.luck_stack.count() - 1, current_index + direction))
        if next_index == current_index:
            return
        if self.luck_stack.is_animating():
            return

        self.luck_stack.slide_to(next_index, direction)

    def apply_wallpaper_palette(
        self,
        surface: str,
        panel: str,
        border: str,
        accent: str,
        muted: str,
        theme_accent: str | None = None,
    ) -> None:
        """Apply wallpaper-derived colors to every tracker surface."""
        accent = theme_accent or accent
        self._palette_accent = accent
        panel_color = QColor(panel)
        surface_color = QColor(surface)
        border_color = QColor(border)
        panel_rgba = (
            f"rgba({panel_color.red()}, {panel_color.green()}, "
            f"{panel_color.blue()}, 224)"
        )
        surface_rgba = (
            f"rgba({surface_color.red()}, {surface_color.green()}, "
            f"{surface_color.blue()}, 166)"
        )
        border_rgba = (
            f"rgba({border_color.red()}, {border_color.green()}, "
            f"{border_color.blue()}, 64)"
        )
        self.setStyleSheet(
            self.styleSheet()
            + f"QFrame#pityTracker {{ background: {panel_rgba}; border-color: {border_rgba}; }}"
            f"QFrame#conveneBannerCard {{ background: {surface_rgba}; border-color: {border_rgba}; }}"
            f"QLabel#conveneBannerCategory, QLabel#conveneBannerPity, "
            f"QLabel#conveneBannerBadge, QPushButton#pityIconButton, "
            f"QPushButton#pityFooter, QLabel#pityOnline {{ color: {accent}; }}"
            f"QLabel#pityMeta {{ color: {muted}; }}"
            f"QLabel#pityStatValue {{ color: {muted}; }}"
            f"QLabel#conveneBannerBadge {{ border-color: {border_rgba}; }}"
            f"QPushButton#pityFooter {{ background: {surface_rgba}; border-color: {border_rgba}; }}"
        )
        self.resonator_card.category_label.setStyleSheet(f"color: {accent};")
        self.weapon_card.category_label.setStyleSheet(f"color: {accent};")
        self.standard_card.category_label.setStyleSheet(f"color: {accent};")
        for card in (self.resonator_card, self.weapon_card, self.standard_card):
            card.art.set_backdrop(panel)
            effect = card.art.graphicsEffect()
            if isinstance(effect, QGraphicsDropShadowEffect):
                shadow_color = QColor(accent)
                shadow_color.setAlpha(160)
                effect.setColor(shadow_color)
        self._refresh_labels()

    def _load_visual_assets(self) -> None:
        self._load_banner_image(
            EVENT_RESONATOR_BANNER_URL,
            self.resonator_card.art,
        )
        self._load_banner_image(
            SIGNATURE_WEAPON_BANNER_URL,
            self.weapon_card.art,
        )

    def _load_banner_image(self, url: str, target: _BannerArtLabel) -> None:
        if not url or not allows_remote_content(url):
            return
        reply = self.image_network.get(QNetworkRequest(QUrl(url)))
        self._image_replies[url] = reply
        reply.finished.connect(lambda: self._finish_banner_image(reply, url, target))

    def _finish_banner_image(
        self,
        reply: QNetworkReply,
        url: str,
        target: _BannerArtLabel,
    ) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError or not reply.isOpen():
                return
            pixmap = QPixmap()
            data = reply.readAll().data() if reply.isOpen() else b""
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                target.set_art(pixmap)
        finally:
            self._image_replies.pop(url, None)

    def _load_image(
        self,
        url: str,
        target: QLabel,
        width: int,
        height: int,
        border_color: str | None = None,
    ) -> None:
        if not url or not allows_remote_content(url):
            return
        reply = self.image_network.get(QNetworkRequest(QUrl(url)))
        self._image_replies[url] = reply
        reply.finished.connect(
            lambda: self._finish_image(reply, url, target, width, height, border_color)
        )

    def _finish_image(
        self,
        reply: QNetworkReply,
        url: str,
        target: QLabel,
        width: int,
        height: int,
        border_color: str | None,
    ) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError or not reply.isOpen():
                return
            pixmap = QPixmap()
            data = reply.readAll().data() if reply.isOpen() else b""
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                target.setPixmap(self._circular_pixmap(pixmap, width, height))
                if border_color:
                    target.setStyleSheet(
                        f"border: 1px solid {border_color}; border-radius: {width // 2}px;"
                    )
        finally:
            self._image_replies.pop(url, None)

    @staticmethod
    def _circular_pixmap(source: QPixmap, width: int, height: int) -> QPixmap:
        return circular_pixmap(source, width, height)

    @staticmethod
    def _make_progress() -> QProgressBar:
        return pity_progress_bar(5)

    pulseValue = Property(float, lambda self: self._pulse_value, lambda self, value: self._set_pulse(value))

    def _set_pulse(self, value: float) -> None:
        self._pulse_value = value
        effect = self.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setBlurRadius(8 + value * 22)
            effect.setColor(QColor(6, 182, 212, int(100 + value * 150)))

    def _refresh_labels(self) -> None:
        resonator = self.state.resonator if self.state.resonator is not None else "--"
        weapon = self.state.weapon if self.state.weapon is not None else "--"
        standard_character = (
            self.state.standard_character
            if self.state.standard_character is not None else "--"
        )
        standard_weapon = (
            self.state.standard_weapon
            if self.state.standard_weapon is not None else "--"
        )
        self.resonator_card.set_pity(self.state.resonator)
        self.weapon_card.set_pity(self.state.weapon)
        self.standard_card.set_pity(self.state.standard_character)
        guarantee = (
            "50/50: Garantido" if self.state.guaranteed is True
            else "50/50: Ativo" if self.state.guaranteed is False
            else "50/50: --"
        )
        recent = self.state.five_star_history[-1] if self.state.five_star_history else "--"
        self.resonator_card.set_badges([guarantee, f"5★ Recente: {recent} pulls"])
        self.weapon_card.set_badges([f"5★ Recente: {recent} pulls"])
        self.standard_card.set_badges([f"Arma: {standard_weapon} / 80"])
        self.standard_weapon.setText(f"Arma: {standard_weapon} / 80")
        total = self.state.total_registered or "--"
        self.footer_stats.setText(f"Total registrado no banco: {total} tiros")
        self.summary_values["pulls"].setText(
            f"{self.state.total_registered:,}" if self.state.total_registered else "--"
        )
        self.summary_values["astrites"].setText(
            f"{self.state.total_registered * 160:,}" if self.state.total_registered else "--"
        )
        self.summary_values["five"].setText(str(len(self.state.five_star_history)))
        self.summary_values["four"].setText(str(self.state.four_star_total))
        current_pity = self.state.resonator
        next_pity = max(0, 80 - current_pity) if current_pity is not None else None
        average = sum(self.state.five_star_history) / len(self.state.five_star_history) if self.state.five_star_history else None
        five_page = self.luck_pages["five"]
        five_page["value"].setText("Sorte 5★: --" if not self.state.five_star_history else "Sorte 5★: registrada")
        five_page["average"].setText(f"Pity médio: {average:.1f}" if average is not None else "Pity médio: --")
        five_page["obtained"].setText(f"5★ obtidos: {len(self.state.five_star_history)}")
        five_page["message"].setText(
            "Boa sequência de sorte" if self.state.five_star_history else "Faça mais giros para desbloquear"
        )
        four_page = self.luck_pages["four"]
        four_page["value"].setText("Sorte 4★: --" if not self.state.four_star_total else "Sorte 4★: registrada")
        four_page["average"].setText("Pity médio: --")
        four_page["obtained"].setText(f"4★ obtidos: {self.state.four_star_total}")
        four_page["message"].setText(
            "Boa sequência de sorte" if self.state.four_star_total else "Faça mais giros para desbloquear"
        )
        self._set_progress(self.resonator_progress, self.state.resonator)
        self._set_progress(self.weapon_progress, self.state.weapon)
        self._render_history_avatars()

    def _render_history_avatars(self) -> None:
        while self.history_row.count():
            item = self.history_row.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        details = self.state.recent_convene_details[:3]
        history = self.state.five_star_history[-3:]
        if details:
            for detail in details:
                badge = QLabel(detail[:18])
                badge.setObjectName("pityHistoryBadge")
                badge.setFixedSize(112, 20)
                badge.setToolTip(detail)
                self.history_row.addWidget(badge)
            self.history_row.addStretch(1)
            return
        if not history:
            empty = QLabel("--")
            empty.setObjectName("pityHistory")
            self.history_row.addWidget(empty)
            return
        for value in reversed(history):
            avatar = QLabel()
            avatar.setObjectName("pityHistoryBadge")
            avatar.setFixedSize(20, 20)
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setText(str(value))
            avatar.setToolTip(f"5★ após {value} tiros")
            self.history_row.addWidget(avatar)
        self.history_row.addStretch(1)

    def _request_sync(self) -> None:
        if self._import_thread is not None and self._import_thread.isRunning():
            return
        if self._pwsh_process is not None:
            if self._pwsh_process.poll() is None:
                return
            self._pwsh_process = None
            self._pwsh_poll_timer.stop()

        self.sync_log_clicked.emit()
        self._start_external_url_discovery()

    def _start_saved_log_import(self) -> None:
        """Use a URL discovered in the current local game logs as the primary source."""
        try:
            capture = ClientLogReader().get_capture_context()
        except (FileNotFoundError, OSError, ValueError) as error:
            self.tracker_status = TrackerStatus(
                log_status="no_convene_url",
                sync_status="error",
                last_sync_at=_utc_now_iso(),
                source="unknown",
                message=str(error),
            )
            self.status_changed.emit(self.tracker_status)
            answer = QMessageBox.question(
                self,
                "Native URL unavailable",
                "Tethys did not find a valid URL in the current logs. "
                "Deseja usar explicitamente o descobridor externo do WuWa Tracker?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._start_external_url_discovery()
            else:
                self._on_sync_error(str(error))
            return

        self.sync_status.setText("URL atual dos logs encontrada")
        self.sync_label.setText("Consultando os registros desta captura...")
        self._start_import(capture.source_url, capture_context=capture)

    def _start_external_url_discovery(self) -> None:
        clipboard = QApplication.clipboard()
        self._clipboard_before_external = clipboard.text() if clipboard is not None else ""
        self.sync_status.setText("Descoberta externa solicitada")
        self.sync_label.setText("Aguardando uma URL nova do WuWa Tracker...")
        try:
            self._pwsh_process = subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoExit",
                    "-Command",
                    WUWA_TRACKER_IMPORT_COMMAND,
                ],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except OSError as error:
            self._on_sync_error(f"Could not start the external URL finder: {error}")
            return
        self._pwsh_poll_timer.start()

    def _await_wuwatracker_import(self) -> None:
        process = self._pwsh_process
        if process is None:
            self._pwsh_poll_timer.stop()
            return
        clipboard = QApplication.clipboard()
        current_text = clipboard.text() if clipboard is not None else ""
        capture = capture_from_changed_clipboard(
            self._clipboard_before_external,
            current_text,
        )
        if capture is not None:
            self._pwsh_process = None
            self._pwsh_poll_timer.stop()
            self._start_import(capture.source_url, capture_context=capture)
            return
        if process.poll() is not None:
            self._pwsh_process = None
            self._pwsh_poll_timer.stop()
            self._on_sync_error(
                "The external URL finder did not provide a new valid clipboard URL."
            )

    def _prepare_capture_context(
        self,
        capture: ConveneCaptureContext,
    ) -> ConveneCaptureContext:
        previous_url = (
            self.last_capture_context.source_url
            if self.last_capture_context is not None
            else None
        )
        prepared = replace(
            capture,
            is_new_capture=(capture.source_url != previous_url),
        )
        self.last_capture_context = prepared
        return prepared

    def request_sync(self) -> None:
        """Start a fresh WuWa Tracker capture through the visible PowerShell."""
        self._request_sync()

    def _on_sync_error(self, message: str) -> None:
        self.sync_status.setText("Não sincronizado")
        self.sync_status.setStyleSheet(
            "color: #FF8F8F; background: rgba(150, 35, 35, 45); "
            "border: 1px solid rgba(255, 143, 143, 100);"
        )
        self.sync_label.setStyleSheet("color: #FF8F8F;")
        self.sync_label.setText("Falha na sincronização")
        self.sync_label.setToolTip(message)
        if (
            message.startswith("Erro HTTP 403:")
            or message.startswith("Erro HTTP 405:")
            or message.startswith("Erro de Conexão/DNS:")
        ):
            self.sync_label.setText(message)
        self.status_changed.emit(self.tracker_status)

    def _set_progress(self, progress: QProgressBar, value: int | None) -> None:
        current = max(0, min(80, value or 0))
        color = self._palette_accent
        progress.setValue(current)
        progress.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,18); border: 0; border-radius: 2px; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
        )

    def _start_import(
        self,
        convene_url: str,
        *,
        capture_context: ConveneCaptureContext | None = None,
    ) -> None:
        try:
            capture = capture_context or _capture_context_from_url(
                convene_url,
                discovery_source="manual_url",
            )
            if capture_context is not None:
                request_context = extract_convene_request_context(convene_url)
                if (
                    capture.source_url != convene_url
                    or capture.player_id.strip() != str(request_context["player_id"])
                    or capture.record_id != str(request_context["record_id"])
                    or capture.svr_id != str(request_context["server_id"])
                    or capture.resources_id != str(request_context["card_pool_id"])
                    or capture.lang != str(request_context["language_code"])
                ):
                    raise ValueError(
                        "The capture context does not match the current Convene URL."
                    )
            player_id = capture.player_id.strip()
            if not player_id:
                raise ValueError("A valid player_id is required for Convene synchronization.")
        except ValueError as error:
            self.tracker_status = TrackerStatus(
                log_status="invalid_url",
                sync_status="error",
                last_sync_at=_utc_now_iso(),
                message=str(error),
            )
            self.sync_status.setText("Client.log inválido")
            self.sync_label.setText(str(error))
            self.status_changed.emit(self.tracker_status)
            return
        capture = self._prepare_capture_context(capture)
        self.tracker_status = TrackerStatus(
            log_status="valid",
            sync_status="running",
            source="api",
            capture_source=capture.discovery_source,
            is_new_capture=capture.is_new_capture,
        )
        self._activate_player_history(player_id)
        self.sync_status.setText("Sincronizando...")
        self._import_thread = QThread(self)
        self._import_worker = PityHistoryImportWorker(convene_url)
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.finished.connect(self._import_worker.deleteLater)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.status.connect(self._apply_tracker_status)
        self._import_worker.imported.connect(self._apply_imported_records)
        self._import_worker.failed.connect(self._import_failed)
        self._import_worker.imported.connect(self._import_thread.quit)
        self._import_worker.failed.connect(self._import_thread.quit)
        self._import_thread.finished.connect(self._clear_import)
        self._import_thread.start()

    def _apply_tracker_status(self, status: object) -> None:
        if not isinstance(status, TrackerStatus):
            return
        if status.last_success_at is None:
            status.last_success_at = self.tracker_status.last_success_at
        capture = self.last_capture_context
        if capture is not None:
            status.capture_source = capture.discovery_source
            status.is_new_capture = capture.is_new_capture
        self.tracker_status = status
        if status.message:
            self.sync_label.setText(status.message)
            self.sync_label.setToolTip(status.message)
        self.status_changed.emit(status)

    def _update_state_from_records(self, records: Sequence[object]) -> None:
        calculated_state = calculate_pity_state(records)
        self.state.resonator = calculated_state.resonator
        self.state.weapon = calculated_state.weapon
        self.state.standard_character = calculated_state.standard_character
        self.state.standard_weapon = calculated_state.standard_weapon
        self.state.five_star_history = calculated_state.five_star_history
        self.state.recent_convene_details = calculated_state.recent_convene_details
        self.state.four_star_total = calculated_state.four_star_total
        self.state.total_registered = calculated_state.total_registered

    @staticmethod
    def _record_sort_key(record: dict[str, object]) -> tuple[int, float]:
        return record_sort_key(record)

    @staticmethod
    def _format_recent_record(record: object) -> str:
        return format_recent_record(record)

    @staticmethod
    def _record_pool(record: dict[str, object]) -> str:
        return record_pool(record)

    def _apply_imported_records(self, records: object) -> None:
        if not isinstance(records, list):
            return
        self.history_records = [
            record for record in records if isinstance(record, dict)
        ]
        self._update_state_from_records(records)
        self.sync_status.setText("Concluído / Sincronizado")
        self.sync_label.setStyleSheet("")
        self.sync_label.setText("Última sincronização: agora")
        self._refresh_labels()
        self.state_changed.emit(self.state)
        self.history_changed.emit(self.history_records)
        self.status_changed.emit(self.tracker_status)

    def apply_local_history_records(self, records: list[dict[str, object]]) -> None:
        """Refresh the visible local history without marking it as a network sync."""
        self.history_records = records
        self._update_state_from_records(records)
        self._refresh_labels()
        self.state_changed.emit(self.state)
        self.history_changed.emit(self.history_records)

    def import_history_json(self, source: str | Path) -> ConveneJsonImportReport:
        """Import a portable history file and refresh this backend's player view."""
        storage = ConveneStorageManager()
        report = storage.import_json_with_report(Path(source))
        if (
            report.format == "wuwa_tracker"
            and report.player_id
            and not self.active_player_id
        ):
            self._activate_player_history(report.player_id)
            display_records = self.history_records
        elif self.active_player_id:
            display_records = storage.load_for_player(self.active_player_id)
        else:
            display_records = []
        self.apply_local_history_records(display_records)
        return report

    def export_history_json(
        self,
        destination: str | Path,
    ) -> dict[str, object] | None:
        """Export the active player's history through Convene storage."""
        player_id = self.active_player_id
        if not player_id:
            return None
        return ConveneStorageManager().export_tethys_history(
            Path(destination),
            player_id=player_id,
        )

    def _import_failed(self, message: str) -> None:
        self.sync_status.setText("Falha na sincronização")
        self.sync_label.setText(
            "Abra a tela de Histórico dentro do Wuthering Waves primeiro e tente novamente."
        )
        if "Erro HTTP 405:" in message or "Erro HTTP 403:" in message:
            self.sync_label.setText(message)
        if message.startswith("Erro de Conexão/DNS:"):
            self.sync_label.setText(message)
        self.sync_label.setToolTip(message)
        self.sync_button.setText("Sincronizar Client.log")
        self.sync_button.setEnabled(True)
        self._refresh_labels()
        self.status_changed.emit(self.tracker_status)

    def _clear_import(self) -> None:
        if self._import_thread is not None:
            self._import_thread.deleteLater()
        self._import_worker = None
        self._import_thread = None
        self.sync_button.setText("Sincronizar Client.log")
        self.sync_button.setEnabled(True)

    def shutdown_workers(self, timeout_ms: int = 5000) -> bool:
        self._pwsh_poll_timer.stop()
        # The visible PowerShell window belongs to the user and stays open.
        # Stop observing it without terminating its process.
        self._pwsh_process = None
        worker = self._import_thread
        if worker is not None and worker.isRunning():
            worker.quit()
            if not worker.wait(timeout_ms):
                return False
        if self._import_thread is not None and not self._import_thread.isRunning():
            self._clear_import()
        return True

    def capture_pull(self, items: Iterable[object]) -> None:
        """Apply one authorized pull result and notify listeners."""
        item_list = list(items)
        if not item_list:
            return
        self.state.resonator = (self.state.resonator or 0) + len(item_list)
        self.state.total_registered += len(item_list)
        self._refresh_labels()
        self.state_changed.emit(self.state)
        self.new_pull_captured.emit(item_list)
        self._pulse_animation.stop()
        self._pulse_animation.start()

    def bind_worker(self, worker: PityTrackerWorker) -> None:
        worker.shot_captured.connect(self.capture_shot)

    def capture_shot(self, shot: dict[str, object]) -> None:
        items = shot.get("items", [])
        if isinstance(items, list):
            self.capture_pull(items)


class NoticeManager:
    """Loads public notices from the official Kuro Games feed and keeps an offline event board."""

    FALLBACK_NOTICES: tuple[dict[str, object], ...] = (
        {
            "category": "Eventos",
            "tag": "Evento",
            "title": "Eventos ativos da versão",
            "status": "Em andamento",
            "summary": "Confira os eventos temporários e resgate as recompensas disponíveis.",
            "rewards": "Astrites e materiais de evolução",
            "accent": "#55C7FF",
            "date": "09-09",
            "image_url": EVENT_RESONATOR_BANNER_URL,
        },
        {
            "category": "Avisos",
            "tag": "Aviso",
            "title": "Avisos do servidor",
            "status": "Atualizado recentemente",
            "summary": "Consulte as comunicações oficiais e alterações importantes do serviço.",
            "rewards": "Informações importantes",
            "accent": "#F0A35B",
            "date": "09-09",
        },
        {
            "category": "Notícias",
            "tag": "Manutenção",
            "title": "Próxima manutenção programada",
            "status": "Agendado",
            "summary": "Programe suas atividades antes da janela de manutenção do servidor.",
            "rewards": "Compensação conforme anúncio oficial",
            "accent": "#F06D6D",
            "date": "09-09",
            "image_url": SIGNATURE_WEAPON_BANNER_URL,
        },
    )

    def __init__(self, endpoint: str | None = None) -> None:
        default_endpoint = os.environ.get("TETHYS_NOTICES_URL", KURO_NEWS_API_URL).strip()
        self.endpoint = (endpoint or default_endpoint).strip()

    @staticmethod
    def _category_from_name(raw_name: str | None) -> str:
        category = str(raw_name or "").strip()
        folded = category.casefold()
        if folded in {"evento", "eventos", "event", "events"}:
            return "Eventos"
        if folded in {"aviso", "avisos", "announcement", "announcements", "notice", "notices"}:
            return "Avisos"
        if folded in {"notícia", "notícias", "news", "news update", "update", "updates"}:
            return "Notícias"
        return "Notícias" if "news" in folded or "notícia" in folded else "Avisos"

    @staticmethod
    def _build_content_url(item: dict[str, object]) -> str:
        identifier = str(item.get("id") or "").strip()
        if identifier:
            return f"{KURO_NEWS_DETAIL_URL}{identifier}"
        return ""

    def fallback(self) -> list[dict[str, object]]:
        return [dict(item) for item in self.FALLBACK_NOTICES]

    def normalize(self, payload: object) -> list[dict[str, object]]:
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], dict):
                data = payload["data"]
                items = data.get("list", data.get("news", data.get("items", [])))
            else:
                items = payload.get("notices", payload.get("events", payload.get("news", [])))
        else:
            items = payload
        if not isinstance(items, list):
            return []
        notices: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            category_name = item.get("categoryName", item.get("category", item.get("type", "Avisos")))
            category = self._category_from_name(str(category_name))
            title = str(item.get("title", item.get("name", "Aviso"))).strip() or "Aviso"
            image_url = str(item.get("coverUrl", item.get("imageUrl", item.get("image_url", item.get("image", ""))))).strip()
            date_value = item.get("createTime", item.get("createdAt", item.get("date", item.get("published_at", "09-09"))))
            notices.append({
                "category": category,
                "tag": category[:-1] if category.endswith("s") else category,
                "title": title,
                "status": str(item.get("status", "Atualizado recentemente")),
                "summary": str(item.get("summary", item.get("description", ""))),
                "rewards": str(item.get("rewards", "")),
                "image_url": image_url,
                "accent": str(item.get("accent", "#55C7FF")),
                "date": self.format_date(date_value),
                "end_at": str(item.get("end_at", item.get("endDate", item.get("ends_at", "")))),
                "content_url": self._build_content_url(item),
            })
        return notices

    @staticmethod
    def format_date(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "09-09"
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone(timedelta(hours=-5))).strftime("%m-%d")
        except ValueError:
            return raw[:10]

    @staticmethod
    def format_remaining(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "Tempo restante indisponível"
        try:
            end_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if end_at.tzinfo is None:
                end_at = end_at.replace(tzinfo=timezone.utc)
            remaining = end_at - datetime.now(timezone.utc)
            seconds = max(0, int(remaining.total_seconds()))
            days, seconds = divmod(seconds, 86400)
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            if days:
                return f"{days:02d}d {hours:02d}h restantes"
            return f"{hours:02d}h {minutes:02d}m {seconds:02d}s restantes"
        except ValueError:
            return "Tempo restante indisponível"

    def load(self) -> list[dict[str, object]]:
        if not self.endpoint:
            return self.fallback()
        try:
            response = requests.get(
                self.endpoint,
                params={"language": "pt", "page": 1, "limit": 10},
                timeout=12,
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError):
                titles = re.findall(r'alt=["\']([^"\']+)["\']', response.text)
                payload = {
                    "events": [
                        {"category": "Eventos", "tag": "Evento", "title": title, "date": "09-09"}
                        for title in titles if len(title) > 4
                    ]
                }
            notices = self.normalize(payload)
            return notices or self.fallback()
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            return self.fallback()


class NoticeLoadWorker(QThread):
    loaded = Signal(list)

    def __init__(self, manager: NoticeManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.manager = manager

    def run(self) -> None:
        self.loaded.emit(self.manager.load())


class NewsFetcherWorker(QThread):
    """Worker dedicated to the official Kuro Games news API."""

    news_loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, manager: NoticeManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.manager = manager

    def run(self) -> None:
        try:
            self.news_loaded.emit(self.manager.load())
        except Exception as error:  # pragma: no cover - defensive for UI thread safety
            self.failed.emit(str(error))
            self.news_loaded.emit(self.manager.fallback())


class NoticeCard(QFrame):
    """Compact event/news card for the lateral board."""

    def __init__(self, notice: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.end_at = notice.get("end_at", "")
        self.setObjectName("noticeCard")
        accent = str(notice.get("accent", "#55C7FF"))
        self.setStyleSheet(
            f"QFrame#noticeCard {{ background: rgba(8, 17, 29, 220); "
            f"border: 1px solid rgba(130, 190, 220, 55); border-left: 3px solid {accent}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 10, 11, 10)
        layout.setSpacing(5)
        image_url = str(notice.get("image_url", ""))
        if image_url.startswith(("https://", "http://")):
            self.image_manager = QNetworkAccessManager(self)
            self.image_label = QLabel()
            self.image_label.setFixedHeight(74)
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setStyleSheet(
                "background: rgba(4, 10, 18, 180); border-radius: 6px; color: #6F8796;"
            )
            self.image_label.setText("Carregando imagem...")
            layout.addWidget(self.image_label)
            reply = self.image_manager.get(QNetworkRequest(QUrl(image_url)))
            reply.finished.connect(lambda: self._set_image(reply))
        top = QHBoxLayout()
        tag = QLabel(str(notice.get("tag", "Aviso")).upper())
        tag.setStyleSheet(f"color: {accent}; font-size: 9px; font-weight: 900;")
        top.addWidget(tag)
        top.addStretch(1)
        status = QLabel(str(notice.get("status", "Atualizado")))
        status.setStyleSheet("color: #A8C1D0; font-size: 9px; font-weight: 700;")
        top.addWidget(status)
        layout.addLayout(top)
        title = QLabel(str(notice.get("title", "Aviso")))
        title.setWordWrap(True)
        title.setStyleSheet("color: #F4F8FC; font-size: 13px; font-weight: 900;")
        layout.addWidget(title)
        summary = QLabel(str(notice.get("summary", "")))
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #A9BBC8; font-size: 10px; line-height: 1.3;")
        layout.addWidget(summary)
        rewards = str(notice.get("rewards", ""))
        if rewards:
            reward_label = QLabel(rewards)
            reward_label.setWordWrap(True)
            reward_label.setStyleSheet(f"color: {accent}; font-size: 9px; font-weight: 800;")
            layout.addWidget(reward_label)

    def _set_image(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError and reply.isOpen():
            pixmap = QPixmap()
            data = reply.readAll().data() if reply.isOpen() else b""
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                self.image_label.setPixmap(
                    pixmap.scaled(
                        self.image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.image_label.setText("")
        reply.deleteLater()


class ElidedNoticeLabel(QLabel):
    """Single-line label that truncates long launcher headlines cleanly."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setText("")
        self.setMinimumWidth(0)

    def resizeEvent(self, event) -> None:
        metrics = QFontMetrics(self.font())
        self.setToolTip(self._full_text)
        self.setText(metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width())))
        super().resizeEvent(event)


class NoticeRow(QFrame):
    """Launcher-style notice row with elided title and right-aligned date."""

    def __init__(self, notice: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.notice = notice
        self.content_url = str(notice.get("content_url") or notice.get("link") or "").strip()
        self.setObjectName("noticeRow")
        self.setMinimumHeight(38)
        self.setMaximumHeight(38)
        self.setStyleSheet(
            "QFrame#noticeRow { background: transparent; border-bottom: 1px solid #2A3038; }"
            "QFrame#noticeRow:hover { background: rgba(255, 255, 255, 0.05); }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(8)
        image_url = str(notice.get("image_url", ""))
        if str(notice.get("category", "")).casefold() == "eventos" and image_url.startswith(("http://", "https://")):
            self.image_manager = QNetworkAccessManager(self)
            self.image_label = QLabel(self)
            self.image_label.setFixedSize(52, 28)
            self.image_label.setStyleSheet("background: #202833; border-radius: 4px;")
            layout.addWidget(self.image_label)
            reply = self.image_manager.get(QNetworkRequest(QUrl(image_url)))
            reply.finished.connect(lambda: self._set_image(reply))
        title = ElidedNoticeLabel(str(notice.get("title", "Aviso")), self)
        title.setStyleSheet("color: #F3F4F5; font-size: 11px; font-weight: 800;")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(title, 1)
        if str(notice.get("category", "")).casefold() == "eventos":
            self.remaining_label = QLabel(NoticeManager.format_remaining(notice.get("end_at", "")))
            self.remaining_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.remaining_label.setStyleSheet("color: #BFC8D1; font-size: 9px; font-weight: 700;")
            self.remaining_label.setFixedWidth(112)
            layout.addWidget(self.remaining_label)
        date = QLabel(str(notice.get("date", "09-09")))
        date.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        date.setStyleSheet("color: #A5ADB5; font-size: 10px; font-weight: 700;")
        date.setFixedWidth(42)
        layout.addWidget(date)

    def mousePressEvent(self, event) -> None:
        if self.content_url:
            QDesktopServices.openUrl(QUrl(self.content_url))
        super().mousePressEvent(event)

    def _set_image(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError and reply.isOpen():
            pixmap = QPixmap()
            data = reply.readAll().data() if reply.isOpen() else b""
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                self.image_label.setPixmap(pixmap.scaled(
                    self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ))
        reply.deleteLater()

    def update_remaining(self, end_at: object) -> None:
        if hasattr(self, "remaining_label"):
            self.remaining_label.setText(NoticeManager.format_remaining(end_at))


class NoticeHeroFrame(QFrame):
    hover_changed = Signal(bool)

    def enterEvent(self, event) -> None:
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_changed.emit(False)
        super().leaveEvent(event)


class PityTrackerWidget(QFrame):
    """Lateral notices and events board replacing the former Convene Tracker."""

    def __init__(
        self,
        active_character: str = "",
        banner_images: dict[str, object] | None = None,
        parent: QWidget | None = None,
        defer_news_load: bool = False,
        defer_hero_images: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("noticeBoard")
        self.setMinimumWidth(320)
        self.setMaximumWidth(360)
        self.setFixedHeight(440)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QFrame#noticeBoard { background: #12161A; border: 0; border-radius: 12px; }"
            "QTabBar { background: transparent; }"
            "QTabBar::tab { color: #8A929A; background: transparent; padding: 8px 13px 7px 0; margin-right: 14px; font-size: 12px; font-weight: 700; border: 0; }"
            "QTabBar::tab:selected { color: #E2B76E; border-bottom: 2px solid #D4A359; }"
            "QScrollArea { background: transparent; border: 0; }"
        )
        self.notices: list[dict[str, object]] = []
        self._active = True
        self.manager = NoticeManager()
        self.worker: NewsFetcherWorker | None = None
        self._hero_pixmap_cache: dict[str, QPixmap] = {}
        self._hero_image_requests: set[str] = set()
        self._hero_image_attempted: set[str] = set()
        self._hero_images_started = not defer_hero_images
        self._performance_mode = False
        self._slide_group: QParallelAnimationGroup | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 8)
        root.setSpacing(0)
        self.slide_timer = QTimer(self)
        self.slide_timer.setInterval(5000)
        self.slide_timer.timeout.connect(lambda: self._change_slide(1))
        self._build_hero(root)
        self.slide_timer.start()
        self.tabs = QTabBar()
        self.tabs.addTab("Avisos")
        self.tabs.addTab("Notícias")
        self.tabs.addTab("Eventos")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        tabs_wrap = QWidget()
        tabs_layout = QHBoxLayout(tabs_wrap)
        tabs_layout.setContentsMargins(14, 3, 12, 0)
        tabs_layout.addWidget(self.tabs)
        tabs_layout.addStretch(1)
        root.addWidget(tabs_wrap)
        self.tabs.currentChanged.connect(self._render_notices)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        self.notice_layout = QVBoxLayout(content)
        self.notice_layout.setContentsMargins(14, 0, 12, 0)
        self.notice_layout.setSpacing(0)
        self.notice_layout.addStretch(1)
        self.scroll_area.setWidget(content)
        root.addWidget(self.scroll_area, 1)
        self.event_timer = QTimer(self)
        self.event_timer.setInterval(1000)
        self.event_timer.timeout.connect(self._refresh_event_times)
        self.event_timer.start()
        if not defer_news_load:
            self._start_notice_load()

    def set_performance_mode(self, enabled: bool) -> None:
        """Pause only the decorative hero carousel; keep event-time updates."""
        if enabled and not self._performance_mode:
            self._finish_interrupted_slide()
        self._performance_mode = enabled
        self._sync_timers()

    def _finish_interrupted_slide(self) -> None:
        group = self._slide_group
        slide_was_running = (
            group is not None
            and group.state() != QAbstractAnimation.State.Stopped
        )
        if group is not None:
            group.stop()
        if (
            slide_was_running
            or not self.hero_next_image.isHidden()
            or self.hero_image.pos() != QPoint(0, 0)
        ):
            incoming = self.hero_next_image.pixmap()
            if incoming is not None and not incoming.isNull():
                self.hero_image.setPixmap(incoming)
            self.hero_image.move(0, 0)
            self.hero_next_image.hide()
            self.hero_next_image.clear()
            self.hero_next_image.move(0, 0)
            self.hero_image.update()
            self.hero_next_image.update()
        self._slide_group = None

    def set_active(self, active: bool) -> None:
        """Pause polling when the Home notice board is outside the viewport."""
        self._active = active
        self._sync_timers()

    def _sync_timers(self) -> None:
        if self._active:
            if not self.event_timer.isActive():
                self.event_timer.start(1000)
        else:
            self.event_timer.stop()

        if self._active and not self._performance_mode and not self.hero.underMouse():
            if not self.slide_timer.isActive():
                self.slide_timer.start(5000)
        else:
            self.slide_timer.stop()

    def _build_hero(self, root: QVBoxLayout) -> None:
        hero = NoticeHeroFrame(self)
        self.hero = hero
        hero.setFixedHeight(174)
        hero.setStyleSheet("QFrame#noticeHero { background: #122432; border-top-left-radius: 12px; border-top-right-radius: 12px; }")
        hero.setObjectName("noticeHero")
        hero_layout = QGridLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        self.hero_image = QLabel(hero)
        self.hero_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_image.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #193B4D,stop:1 #0A151D); border-top-left-radius: 12px; border-top-right-radius: 12px;")
        self.hero_image.setText("")
        hero_layout.addWidget(self.hero_image, 0, 0)
        self.hero_next_image = QLabel(hero)
        self.hero_next_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_next_image.setStyleSheet(self.hero_image.styleSheet())
        self.hero_next_image.hide()
        hero_layout.addWidget(self.hero_next_image, 0, 0)
        logo = QLabel("WUTHERING\nWAVES", hero)
        logo.setStyleSheet("color: white; font-size: 23px; font-weight: 900; letter-spacing: 1px; background: transparent;")
        logo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        logo.setContentsMargins(16, 0, 0, 0)
        hero_layout.addWidget(logo, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.hero_dots = QLabel("◆  ○")
        self.hero_dots.setStyleSheet("color: #E2B76E; font-size: 12px; font-weight: 900; background: transparent;")
        hero_layout.addWidget(self.hero_dots, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.btn_prev = QPushButton("◀", hero)
        self.btn_next = QPushButton("▶", hero)
        for button in (self.btn_prev, self.btn_next):
            button.setFixedSize(30, 30)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton { color: #E2B76E; background: rgba(8, 12, 17, 180); "
                "border: 1px solid rgba(226, 183, 110, 180); border-radius: 15px; "
                "font-size: 13px; font-weight: 900; padding: 0; }"
                "QPushButton:hover { background: rgba(226, 183, 110, 55); }"
            )
            button.hide()
        hero_layout.addWidget(self.btn_prev, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hero_layout.addWidget(self.btn_next, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.btn_prev.clicked.connect(lambda: self._change_slide(-1))
        self.btn_next.clicked.connect(lambda: self._change_slide(1))
        hero.hover_changed.connect(self._set_hero_hover)
        self.hero_images = (EVENT_RESONATOR_BANNER_URL, SIGNATURE_WEAPON_BANNER_URL)
        self.hero_pixmaps = [QPixmap(), QPixmap()]
        self.hero_index = 0
        self.hero_manager = QNetworkAccessManager(self)
        if self._hero_images_started:
            self._request_hero_images()
        root.addWidget(hero)

    def _set_hero_hover(self, hovered: bool) -> None:
        self.btn_prev.setVisible(hovered)
        self.btn_next.setVisible(hovered)
        self._sync_timers()

    def _request_hero_images(self) -> None:
        self.hero_pixmaps = [
            self._hero_pixmap_cache.get(image_url, QPixmap())
            for image_url in self.hero_images
        ]
        for image_url in dict.fromkeys(self.hero_images):
            if image_url in self._hero_image_attempted:
                continue
            self._hero_image_attempted.add(image_url)
            self._hero_image_requests.add(image_url)
            reply = self.hero_manager.get(QNetworkRequest(QUrl(image_url)))
            reply.finished.connect(
                lambda image_url=image_url, reply=reply:
                self._set_hero_image(reply, image_url)
            )
        current = self.hero_pixmaps[self.hero_index]
        if not current.isNull():
            self._display_hero_pixmap(current)

    def start_hero_image_load(self) -> None:
        if self._hero_images_started:
            return
        self._hero_images_started = True
        self._request_hero_images()

    def _set_hero_image(self, reply: QNetworkReply, image_url: str) -> None:
        self._hero_image_requests.discard(image_url)
        if reply.error() == QNetworkReply.NetworkError.NoError and reply.isOpen():
            pixmap = QPixmap()
            data = reply.readAll().data() if reply.isOpen() else b""
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                self._hero_pixmap_cache[image_url] = pixmap
                for index, current_url in enumerate(self.hero_images):
                    if current_url == image_url:
                        self.hero_pixmaps[index] = pixmap
                if self.hero_images[self.hero_index] == image_url:
                    self._display_hero_pixmap(pixmap)
        reply.deleteLater()

    def _display_hero_pixmap(self, pixmap: QPixmap) -> None:
        self.hero_image.setPixmap(pixmap.scaled(
            self.hero_image.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _change_slide(self, direction: int) -> None:
        slide_group = self._slide_group
        if slide_group is not None and slide_group.state() == QAbstractAnimation.State.Running:
            return
        next_index = (self.hero_index + direction) % len(self.hero_images)
        pixmap = self.hero_pixmaps[next_index]
        self.hero_index = next_index
        self.hero_dots.setText("  ".join("◆" if index == self.hero_index else "○" for index in range(len(self.hero_images))))
        if pixmap.isNull():
            return
        width = max(1, self.hero.width())
        self.hero_next_image.setPixmap(pixmap.scaled(
            self.hero_next_image.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self.hero_image.move(0, 0)
        self.hero_next_image.move(direction * width, 0)
        self.hero_next_image.show()
        current_animation = QPropertyAnimation(self.hero_image, b"pos", self)
        incoming_animation = QPropertyAnimation(self.hero_next_image, b"pos", self)
        for animation in (current_animation, incoming_animation):
            animation.setDuration(280)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        current_animation.setStartValue(QPoint(0, 0))
        current_animation.setEndValue(QPoint(-direction * width, 0))
        incoming_animation.setStartValue(QPoint(direction * width, 0))
        incoming_animation.setEndValue(QPoint(0, 0))
        group = QParallelAnimationGroup(self)
        group.addAnimation(current_animation)
        group.addAnimation(incoming_animation)

        def finish() -> None:
            self.hero_image.setPixmap(self.hero_next_image.pixmap())
            self.hero_image.move(0, 0)
            self.hero_next_image.hide()
            self.hero_next_image.move(0, 0)

        group.finished.connect(finish)
        self._slide_group = group
        group.start()

    def start_news_load(
        self,
        finished_callback: Callable[[], None] | None = None,
    ) -> None:
        self._start_notice_load(finished_callback)

    def _start_notice_load(
        self,
        finished_callback: Callable[[], None] | None = None,
    ) -> None:
        if self.worker is not None:
            return
        self.worker = NewsFetcherWorker(self.manager, self)
        self.worker.news_loaded.connect(self._set_notices)
        self.worker.failed.connect(lambda message: self._set_notices(self.manager.fallback()))
        if finished_callback is not None:
            self.worker.finished.connect(finished_callback)
        self.worker.start()

    def _set_notices(self, notices: list[dict[str, object]]) -> None:
        self.notices = notices
        hero_images = [
            str(notice.get("image_url", "")).strip()
            for notice in notices
            if str(notice.get("image_url", "")).strip()
        ]
        if hero_images:
            self.hero_images = tuple(hero_images[:3])
        else:
            self.hero_images = (EVENT_RESONATOR_BANNER_URL, SIGNATURE_WEAPON_BANNER_URL)
        self.hero_index = min(self.hero_index, len(self.hero_images) - 1)
        self._request_hero_images()
        self._render_notices()

    def _render_notices(self) -> None:
        while self.notice_layout.count() > 1:
            item = self.notice_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        selected = self.tabs.tabText(self.tabs.currentIndex())
        filtered = [
            notice for notice in self.notices
            if str(notice.get("category", "")).casefold() == selected.casefold()
        ]
        for notice in filtered:
            self.notice_layout.insertWidget(self.notice_layout.count() - 1, NoticeRow(notice))

    def _refresh_event_times(self) -> None:
        for index in range(self.notice_layout.count() - 1):
            item = self.notice_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, NoticeRow):
                widget.update_remaining(getattr(widget, "end_at", ""))
