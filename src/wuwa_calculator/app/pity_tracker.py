"""Compact real-time pity tracker UI fed by an authorized local source."""

from __future__ import annotations

import os
import sys
import re
import json
import requests
from dataclasses import dataclass, field
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
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
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
from src.wuwa_calculator.app.styles import wallpaper_palette
from src.wuwa_calculator.storage.convene_storage import ConveneStorageManager
EVENT_RESONATOR_BANNER_URL = "https://i.imgur.com/JrRW9Bt.jpeg"
SIGNATURE_WEAPON_BANNER_URL = "https://i.imgur.com/metoowt.jpeg"
CONVENE_URL_PREFIX = "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html#"
CONVENE_LOG_PATH = Path(
    r"D:\Wuthering Waves\Wuthering Waves Game\Client\Saved\Logs\Client.log"
)
KURO_NEWS_API_URL = "https://wutheringwaves.kurogames.com/api/news/list"
KURO_NEWS_DETAIL_URL = "https://wutheringwaves.kurogames.com/pt/main/news/detail/"
CONVENE_LOG_URL_RE = re.compile(r"https://aki-gm-resources[^\s\"']+")
CONVENE_GACHA_URL_RE = re.compile(r"https?://[^\s\"]+gacha[^\s\"]+", re.IGNORECASE)
CONVENE_URL_NOT_FOUND_MESSAGE = (
    "URL não encontrada. Abra a tela de Convene no jogo e tente novamente."
)
CONVENE_DNS_ERROR_MESSAGE = (
    "Erro de Conexão/DNS: Não foi possível alcançar o servidor da Kuro Games. "
    "Verifique sua internet ou firewall."
)
KURO_RECORD_API_URLS = (
    "https://gm-server-gacha.aki-game.net/gacha/getGachaRecord",
    "https://aki-gm-resources-oversea.aki-game.net/gacha/getGachaRecord",
)
KURO_RECORD_API_URL = KURO_RECORD_API_URLS[0]
CONVENE_PLAYER_ID_RE = re.compile(
    r"(?:player_id|playerId)=([a-zA-Z0-9]+)", re.IGNORECASE
)
CONVENE_RECORD_ID_RE = re.compile(
    r"(?:record_id|recordId)=([a-zA-Z0-9]+)", re.IGNORECASE
)


def _normalize_pull_record(
    record: dict[str, object],
    source: str = "convene_api",
) -> dict[str, object]:
    timestamp = record.get("timestamp", record.get("time", record.get("date")))
    name = record.get("name", record.get("item", record.get("title")))
    rarity = record.get("rarity", record.get("quality", record.get("rank")))
    pool = record.get("pool", record.get("type", record.get("gacha_type")))
    if pool in (None, ""):
        pool = LegacyPityTrackerWidget._record_pool(record)
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
    message: str = ""
    new_records_count: int = 0
    pool_status: dict[str, dict[str, object]] = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_age(records: list[dict[str, object]]) -> float | None:
    timestamps: list[float] = []
    for record in records:
        value = record.get("timestamp", record.get("time", record.get("date")))
        try:
            if isinstance(value, (int, float)):
                timestamps.append(float(value))
            else:
                text = str(value or "").strip().replace("Z", "+00:00")
                timestamps.append(datetime.fromisoformat(text).timestamp())
        except (TypeError, ValueError, OverflowError):
            continue
    if not timestamps:
        return None
    return max(0.0, datetime.now(timezone.utc).timestamp() - max(timestamps))


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
        message=message,
        pool_status=dict(pool_statuses),
    )


def extract_convene_parameters(url: str) -> tuple[str, str]:
    """Extract authentication parameters from query strings or URL fragments."""
    clean_url = unquote(url.replace("\r", "").replace("\n", "").strip())
    player_match = CONVENE_PLAYER_ID_RE.search(clean_url)
    record_match = CONVENE_RECORD_ID_RE.search(clean_url)
    player_id = player_match.group(1) if player_match else ""
    record_id = record_match.group(1) if record_match else ""
    if not player_id or not record_id:
        raise ValueError("A Convene Record URL não contém player_id e record_id.")
    return player_id, record_id


def fetch_convene_records(
    convene_url: str,
    *,
    pool_statuses: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Fetch records for every known banner pool using the official API."""
    player_id, record_id = extract_convene_parameters(convene_url)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    records: list[dict[str, object]] = []
    for pool_type in range(1, 9):
        pool_key = str(pool_type)
        if pool_statuses is not None:
            pool_statuses[pool_key] = {
                "status": "started",
                "completed": False,
                "record_count": 0,
            }
        response = None
        last_error = ""
        payload = {
            "playerId": player_id,
            "cardPoolType": pool_type,
            "language": "en",
            "recordId": record_id,
        }
        for endpoint in KURO_RECORD_API_URLS:
            try:
                response = requests.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=15,
                )
            except requests.exceptions.ConnectionError:
                last_error = CONVENE_DNS_ERROR_MESSAGE
                continue
            if response.status_code == 405:
                try:
                    response = requests.get(
                        endpoint,
                        params=payload,
                        headers={"User-Agent": headers["User-Agent"], "Accept": "application/json"},
                        timeout=15,
                    )
                except requests.exceptions.ConnectionError:
                    last_error = CONVENE_DNS_ERROR_MESSAGE
                    continue
            if response.status_code in (403, 405):
                continue
            break
        if response is None:
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": last_error or CONVENE_DNS_ERROR_MESSAGE,
                })
                continue
            raise requests.exceptions.ConnectionError(CONVENE_DNS_ERROR_MESSAGE)
        if response.status_code in (403, 405):
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": f"Erro HTTP {response.status_code}",
                })
                continue
            raise RuntimeError(
                f"Erro HTTP {response.status_code}: Método de requisição recusado pelo servidor da Kuro."
            )
        if response.status_code != 200:
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": f"Erro HTTP {response.status_code}",
                })
            continue
        if not response.text.strip():
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "success_empty",
                    "completed": True,
                })
            continue
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": "Resposta JSON inválida",
                })
            continue
        if not isinstance(payload, dict) or payload.get("code", 0) not in (0, "0"):
            if pool_statuses is not None:
                pool_statuses[pool_key].update({
                    "status": "error",
                    "completed": True,
                    "message": "Resposta da API inválida",
                })
            continue
        data = payload.get("data", [])
        pool_records = PityHistoryImportWorker._extract_records(data)
        records.extend(pool_records)
        if pool_statuses is not None:
            pool_statuses[pool_key].update({
                "status": "success" if pool_records else "success_empty",
                "completed": True,
                "record_count": len(pool_records),
            })
    if not records:
        raise ValueError("Nenhum registro retornado; o token pode estar expirado.")
    return records


def get_convene_url_from_log(log_path: str | Path | None = None) -> str:
    """Return the latest Convene URL from a standard Wuthering Waves log."""
    candidates = [
        Path(os.path.expanduser(
            r"~\AppData\LocalLow\Kuro Game\Wuthering Waves\Saved\Logs\Client.log"
        )),
        CONVENE_LOG_PATH,
    ]
    if log_path is not None:
        candidates = [Path(log_path)]

    selected_path = next((path for path in candidates if path.exists()), None)
    if selected_path is None:
        raise FileNotFoundError(CONVENE_URL_NOT_FOUND_MESSAGE)
    with selected_path.open("r", encoding="utf-8", errors="ignore") as file:
        log_content = file.read()
    if not log_content.strip():
        raise ValueError("Client.log vazio; abra a tela de Convene no jogo e tente novamente.")
    matches = CONVENE_GACHA_URL_RE.findall(log_content)
    if not matches:
        raise ValueError(CONVENE_URL_NOT_FOUND_MESSAGE)
    return matches[-1]


class ClientLogReader:
    """Native reader for the Wuthering Waves Client.log file."""

    def __init__(self, log_path: str | Path | None = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else None

    def get_convene_url(self) -> str:
        return get_convene_url_from_log(self.log_path)


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


@dataclass
class PityState:
    resonator: int | None = None
    weapon: int | None = None
    standard_character: int | None = None
    standard_weapon: int | None = None
    guaranteed: bool | None = None
    five_star_history: list[int] = field(default_factory=list)
    recent_convene_details: list[str] = field(default_factory=list)
    total_registered: int = 0
    four_star_total: int = 0


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
            raw_records = fetch_convene_records(
                self.history_url,
                pool_statuses=pool_statuses,
            )
            normalized_records = [
                _normalize_pull_record(record)
                for record in raw_records
                if isinstance(record, dict)
            ]
            persistable_records = [
                record for record in normalized_records
                if record.get("is_pull", True)
            ]
            partial = _pool_results_are_partial(pool_statuses)
            finished_at = _utc_now_iso()
            if persistable_records:
                try:
                    history, new_records_count = ConveneStorageManager().merge_with_metadata(
                        persistable_records
                    )
                    non_pull_records = [
                        record for record in normalized_records
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
                        message="Sincronização parcial" if partial else "Sincronização concluída",
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
                    self.imported.emit(normalized_records)
            else:
                self.status.emit(TrackerStatus(
                    api_status="success_empty",
                    history_status="unchanged",
                    sync_status="success_no_new",
                    last_sync_at=finished_at,
                    last_success_at=finished_at,
                    history_age=None,
                    is_partial=partial,
                    source="api",
                    message="Nenhuma pull normalizada retornada",
                    pool_status=dict(pool_statuses),
                ))
                self.imported.emit(normalized_records)
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
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            if any(key in data for key in ("name", "item", "quality", "rarity", "rank", "time")):
                return [data]
            for key in ("list", "records", "history", "items", "rows", "pulls", "result", "data"):
                records = PityHistoryImportWorker._extract_records(data.get(key))
                if records:
                    return records
        return []


class ConveneSyncWorker(QThread):
    """Read the latest Convene URL and fetch its JSON payload off the UI thread."""

    convene_data_loaded = Signal(dict)
    sync_failed = Signal(str)
    success_signal = Signal(object)
    error_signal = Signal(str)

    def __init__(self, log_path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.log_path = Path(log_path) if log_path is not None else None

    def run(self) -> None:
        try:
            reader = ClientLogReader(self.log_path)
            convene_url = reader.get_convene_url()
            response = requests.get(
                convene_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/json, text/plain, */*",
                },
                timeout=15,
            )
            if response.status_code in (403, 405):
                raise ValueError(
                    f"Erro HTTP {response.status_code}: Método de requisição recusado pelo servidor da Kuro."
                )
            if response.status_code != 200:
                raise ValueError("Sessão expirada. Acesse o Convene no jogo para revalidar.")
            if not response.text.strip():
                raise ValueError("Sessão expirada. Acesse o Convene no jogo para revalidar.")
            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError as error:
                raise ValueError(
                    "Sessão expirada. Acesse o Convene no jogo para revalidar."
                ) from error
            if not isinstance(payload, dict):
                raise ValueError("Sessão expirada. Acesse o Convene no jogo para revalidar.")
            if payload.get("code") not in (None, 0, "0"):
                raise ValueError("Sessão expirada. Acesse o Convene no jogo para revalidar.")
            self.convene_data_loaded.emit(payload)
            self.success_signal.emit(payload)
        except requests.RequestException as error:
            self._emit_error(f"Falha de rede ao sincronizar o Convene: {error}")
        except (FileNotFoundError, OSError, ValueError) as error:
            self._emit_error(str(error))
        except Exception as error:  # pylint: disable=broad-except
            self._emit_error(f"Falha ao sincronizar o Convene: {error}")

    def _emit_error(self, message: str) -> None:
        self.sync_failed.emit(message)
        self.error_signal.emit(message)


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
        self._sync_worker: ConveneSyncWorker | None = None
        self.tracker_status = TrackerStatus()
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

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QFrame#pityTracker { background: rgba(15, 17, 26, 224); "
            "border: 1px solid rgba(168, 85, 247, 215); border-radius: 16px; }"
            "QFrame#pityTile { background: rgba(9, 12, 22, 120); "
            "border: 1px solid rgba(6, 182, 212, 130); border-radius: 10px; }"
            "QLabel#pityCardTitle { color: #FFFFFF; font-size: 9px; font-weight: 900; }"
            "QLabel#pityValue { color: #FFFFFF; font-size: 22px; font-weight: 900; "
            "padding: 0; min-height: 27px; }"
            "QLabel#pityResonatorAvatar, QLabel#pityWeaponAvatar { background: rgba(8, 10, 18, 220); "
            "border-radius: 18px; padding: 1px; }"
            "QLabel#pityStandardIcon { color: #7DD3FC; background: rgba(14, 165, 233, 35); "
            "border: 1px solid #38BDF8; border-radius: 18px; padding: 1px; }"
            "QLabel#pityBadge { color: #9DEBFF; background: rgba(6, 182, 212, 35); "
            "border: 1px solid rgba(6, 182, 212, 130); border-radius: 9px; "
            "padding: 4px 8px; font-size: 9px; font-weight: 900; }"
            "QLabel#pitySubtitle { color: #10b981; font-size: 10px; font-weight: 800; }"
            "QLabel#pityMeta { color: #C9C6D9; font-size: 9px; }"
            "QLabel#pityHistory { color: #E7D7FF; font-size: 9px; }"
            "QPushButton#pityIconButton { color: #CFEFFF; background: rgba(9, 20, 35, 180); "
            "border: 1px solid rgba(96, 165, 250, 150); border-radius: 8px; "
            "font-size: 14px; font-weight: 900; padding: 0; }"
            "QPushButton#pityIconButton:hover, QPushButton#pityFooter:hover { "
            "background: rgba(6, 182, 212, 55); border-color: #7DEBFF; }"
            "QPushButton#pityFooter { color: #CFEFFF; background: rgba(9, 20, 35, 180); "
            "border: 1px solid rgba(6, 182, 212, 120); border-radius: 8px; "
            "padding: 6px 8px; font-size: 9px; font-weight: 800; }"
            "QLabel#pityHistoryBadge { color: #F8E7FF; background: rgba(168, 85, 247, 90); "
            "border: 1px solid #A855F7; border-radius: 10px; font-size: 8px; font-weight: 900; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 9)
        root.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(5)
        tracker_badge = QLabel("[ CONVENE TRACKER ]")
        tracker_badge.setObjectName("pityBadge")
        header.addWidget(tracker_badge)
        header.addStretch(1)
        sync_button = QPushButton("↻")
        sync_button.setObjectName("pityIconButton")
        sync_button.setFixedSize(28, 28)
        sync_button.setToolTip("Sync Log")
        sync_button.clicked.connect(self._request_sync)
        self.sync_button = sync_button
        export_button = QPushButton("⇩")
        export_button.setObjectName("pityIconButton")
        export_button.setFixedSize(28, 28)
        export_button.setToolTip("Export")
        export_button.clicked.connect(self.export_data_clicked)
        header.addWidget(sync_button)
        header.addWidget(export_button)
        root.addLayout(header)

        subtitle = QLabel("●  Sniffer em Tempo Real: ONLINE")
        subtitle.setObjectName("pitySubtitle")
        root.addWidget(subtitle)

        self.sync_label = QLabel("◷  Última sincronização por Log: --")
        self.sync_label.setObjectName("pityMeta")
        self.sync_label.hide()
        pity_grid = QGridLayout()
        pity_grid.setContentsMargins(0, 0, 0, 0)
        pity_grid.setHorizontalSpacing(6)
        pity_grid.setVerticalSpacing(6)

        self.resonator_card = self._make_pity_tile("RESONATOR", "pityResonatorAvatar")
        self.resonator_avatar = QLabel(self.resonator_card)
        self.resonator_avatar.setObjectName("pityResonatorAvatar")
        self.resonator_avatar.setGeometry(108, 28, 36, 36)
        self.resonator_avatar.setFixedSize(36, 36)
        self.resonator_avatar.setScaledContents(True)
        resonator_value = QLabel(self.resonator_card)
        resonator_value.setObjectName("pityValue")
        self.resonator_value = resonator_value
        self.resonator_value.setGeometry(10, 27, 94, 29)
        self.resonator_progress = self._make_progress()
        self.resonator_progress.setGeometry(10, 61, 94, 5)
        self.guarantee_label = QLabel(self.resonator_card)
        self.guarantee_label.setObjectName("pityMeta")
        self.guarantee_label.setGeometry(10, 70, 130, 16)
        pity_grid.addWidget(self.resonator_card, 0, 0)

        self.weapon_card = self._make_pity_tile("WEAPON", "pityWeaponAvatar")
        self.weapon_avatar = QLabel(self.weapon_card)
        self.weapon_avatar.setObjectName("pityWeaponAvatar")
        self.weapon_avatar.setGeometry(108, 28, 36, 36)
        self.weapon_avatar.setFixedSize(36, 36)
        self.weapon_avatar.setScaledContents(True)
        self.weapon_value = QLabel(self.weapon_card)
        self.weapon_value.setObjectName("pityValue")
        self.weapon_value.setGeometry(10, 27, 94, 29)
        self.weapon_progress = self._make_progress()
        self.weapon_progress.setGeometry(10, 61, 94, 5)
        pity_grid.addWidget(self.weapon_card, 0, 1)

        self.standard_character_card = self._make_pity_tile("STD CHAR", "pityStandardIcon")
        self.standard_character_icon = QLabel("◆", self.standard_character_card)
        self.standard_character_icon.setObjectName("pityStandardIcon")
        self.standard_character_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.standard_character_icon.setGeometry(108, 28, 36, 36)
        self.standard_character_icon.setFixedSize(36, 36)
        self.standard_character_icon.setScaledContents(True)
        self.standard_character = QLabel(self.standard_character_card)
        self.standard_character.setObjectName("pityValue")
        self.standard_character.setGeometry(10, 27, 94, 29)
        pity_grid.addWidget(self.standard_character_card, 1, 0)

        self.standard_weapon_card = self._make_pity_tile("STD WEAPON", "pityStandardIcon")
        self.standard_weapon_icon = QLabel("◆", self.standard_weapon_card)
        self.standard_weapon_icon.setObjectName("pityStandardIcon")
        self.standard_weapon_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.standard_weapon_icon.setGeometry(108, 28, 36, 36)
        self.standard_weapon_icon.setFixedSize(36, 36)
        self.standard_weapon_icon.setScaledContents(True)
        self.standard_weapon = QLabel(self.standard_weapon_card)
        self.standard_weapon.setObjectName("pityValue")
        self.standard_weapon.setGeometry(10, 27, 94, 29)
        pity_grid.addWidget(self.standard_weapon_card, 1, 1)
        root.addLayout(pity_grid)

        footer_row = QHBoxLayout()
        footer_row.setSpacing(5)
        recent_label = QLabel("Recent Convene Details")
        recent_label.setObjectName("pityMeta")
        footer_row.addWidget(recent_label)
        self.history_row = QHBoxLayout()
        self.history_row.setSpacing(4)
        footer_row.addLayout(self.history_row)
        footer_row.addStretch(1)
        root.addLayout(footer_row)
        footer_stats = QLabel()
        footer_stats.setObjectName("pityMeta")
        root.addWidget(footer_stats)
        self.footer_stats = footer_stats
        history_button = QPushButton("Ver Histórico Completo  >")
        history_button.setObjectName("pityFooter")
        history_button.clicked.connect(self.view_history_clicked)
        root.addWidget(history_button)
        self._refresh_labels()

    @staticmethod
    def _make_pity_tile(title: str, avatar_name: str) -> QFrame:
        tile = QFrame()
        tile.setObjectName("pityTile")
        tile.setFixedHeight(94)
        title_label = QLabel(title, tile)
        title_label.setObjectName("pityCardTitle")
        title_label.setGeometry(10, 8, 110, 16)
        return tile

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
            data = bytes(reply.readAll()) if reply.isOpen() else b""
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
            data = bytes(reply.readAll()) if reply.isOpen() else b""
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
        scaled = source.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(width, height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, width, height)
        painter.setClipPath(path)
        x = (width - scaled.width()) // 2
        y = (height - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        return canvas

    @staticmethod
    def _make_progress() -> QProgressBar:
        progress = QProgressBar()
        progress.setRange(0, 80)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setFixedHeight(5)
        return progress

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
            if item.widget() is not None:
                item.widget().deleteLater()
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
        self.sync_log_clicked.emit()
        self._start_saved_log_import()

    def _start_saved_log_import(self) -> None:
        """Use the saved local Client.log without external import scripts."""
        try:
            convene_url = ClientLogReader().get_convene_url()
        except FileNotFoundError as error:
            self.tracker_status = TrackerStatus(
                log_status="missing",
                sync_status="error",
                last_sync_at=_utc_now_iso(),
                message=str(error),
            )
            self._on_sync_error(str(error))
            return
        except OSError as error:
            self.tracker_status = TrackerStatus(
                log_status="unknown",
                sync_status="error",
                last_sync_at=_utc_now_iso(),
                message=str(error),
            )
            self._on_sync_error(str(error))
            return
        except ValueError as error:
            message = str(error)
            log_status = "empty" if message.startswith("Client.log vazio") else "no_convene_url"
            self.tracker_status = TrackerStatus(
                log_status=log_status,
                sync_status="error",
                last_sync_at=_utc_now_iso(),
                message=message,
            )
            self._on_sync_error(str(error))
            return
        self.tracker_status = TrackerStatus(
            log_status="valid",
            sync_status="running",
            source="api",
        )
        self.sync_status.setText("URL do Client.log encontrada")
        self.sync_label.setText("Consultando os registros salvos...")
        self._start_import(convene_url)

    def _start_convene_sync(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        self.sync_button.setEnabled(False)
        self.sync_button.setText("Carregando...")
        self.sync_status.setText("Sincronizando...")
        self.sync_label.setStyleSheet("color: #F4C7C3;")
        self.sync_label.setText("Lendo Client.log e consultando a API...")
        self._sync_worker = ConveneSyncWorker(parent=self)
        self._sync_worker.convene_data_loaded.connect(self.on_convene_data_received)
        self._sync_worker.sync_failed.connect(self._on_sync_error)
        self._sync_worker.finished.connect(self._clear_sync_worker)
        self._sync_worker.start()

    def on_convene_data_received(self, data: dict) -> None:
        """Apply a successful API payload to every Convene Tracker surface."""
        records = PityHistoryImportWorker._extract_records(data)
        if not records:
            self._on_sync_error("A API não retornou registros de Convene reconhecíveis.")
            return
        self._apply_imported_records(records)
        self.sync_status.setText("ONLINE / Sincronizado")
        self.sync_status.setStyleSheet(
            "color: #6FE0B0; background: rgba(35, 150, 105, 45); "
            "border: 1px solid rgba(111, 224, 176, 100);"
        )
        self.update()
        self.repaint()

    def update_convene_ui(self, data: object) -> None:
        """Backward-compatible alias for the Convene data handler."""
        if isinstance(data, dict):
            self.on_convene_data_received(data)

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

    def _clear_sync_worker(self) -> None:
        if self._sync_worker is not None:
            self._sync_worker.deleteLater()
        self._sync_worker = None
        self.sync_button.setText("Sincronizar Client.log")
        self.sync_button.setEnabled(True)

    def _set_progress(self, progress: QProgressBar, value: int | None) -> None:
        current = max(0, min(80, value or 0))
        color = self._palette_accent
        progress.setValue(current)
        progress.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,18); border: 0; border-radius: 2px; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
        )

    def _start_import(self, convene_url: str) -> None:
        try:
            extract_convene_parameters(convene_url)
        except ValueError as error:
            self.tracker_status = TrackerStatus(
                log_status="invalid_url",
                sync_status="error",
                last_sync_at=_utc_now_iso(),
                message=str(error),
            )
            self.sync_status.setText("Client.log inválido")
            self.sync_label.setText(str(error))
            return
        self.sync_status.setText("Sincronizando...")
        self._import_thread = QThread(self)
        self._import_worker = PityHistoryImportWorker(convene_url)
        self._import_worker.moveToThread(self._import_thread)
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
        self.tracker_status = status

    def _update_state_from_records(self, records: list[object]) -> None:
        ordered_records = sorted(
            (record for record in records if isinstance(record, dict)),
            key=self._record_sort_key,
        )
        pity_by_pool = {
            "resonator": 0,
            "weapon": 0,
            "standard_character": 0,
            "standard_weapon": 0,
        }
        five_stars: list[int] = []
        four_stars = 0
        for record in ordered_records:
            pool = self._record_pool(record)
            pity_by_pool[pool] += 1
            rarity = record.get("quality", record.get("rarity", record.get("rank", 0)))
            try:
                rarity_value = int(rarity)
            except (TypeError, ValueError):
                continue
            if rarity_value >= 5:
                five_stars.append(pity_by_pool[pool])
                pity_by_pool[pool] = 0
            elif rarity_value >= 4:
                four_stars += 1
        self.state.resonator = pity_by_pool["resonator"]
        self.state.weapon = pity_by_pool["weapon"]
        self.state.standard_character = pity_by_pool["standard_character"]
        self.state.standard_weapon = pity_by_pool["standard_weapon"]
        self.state.five_star_history = five_stars
        self.state.recent_convene_details = [
            self._format_recent_record(record) for record in ordered_records[-5:]
        ]
        self.state.four_star_total = four_stars
        self.state.total_registered = len(ordered_records)

    @staticmethod
    def _record_sort_key(record: dict[str, object]) -> tuple[int, float]:
        value = record.get("timestamp", record.get("time", record.get("date")))
        try:
            if isinstance(value, (int, float)):
                return (0, float(value))
            text = str(value or "").strip().replace("Z", "+00:00")
            return (0, datetime.fromisoformat(text).timestamp())
        except (TypeError, ValueError, OverflowError):
            return (1, 0.0)

    @staticmethod
    def _format_recent_record(record: object) -> str:
        if not isinstance(record, dict):
            return str(record)
        name = record.get("name", record.get("item", record.get("title", "Convene")))
        rarity = record.get("quality", record.get("rarity", record.get("rank", "?")))
        return f"{name} ({rarity}★)"

    @staticmethod
    def _record_pool(record: dict[str, object]) -> str:
        metadata = " ".join(
            str(record.get(key, ""))
            for key in ("type", "pool", "banner", "gacha_type", "resource", "name")
        ).casefold()
        is_weapon = "weapon" in metadata or "arma" in metadata
        is_standard = any(value in metadata for value in ("standard", "permanent", "novice", "常驻"))
        if is_standard and is_weapon:
            return "standard_weapon"
        if is_standard:
            return "standard_character"
        if is_weapon:
            return "weapon"
        return "resonator"

    def _apply_imported_records(self, records: object) -> None:
        if not isinstance(records, list):
            return
        self._update_state_from_records(records)
        self.sync_status.setText("Concluído / Sincronizado")
        self.sync_label.setStyleSheet("")
        self.sync_label.setText("Última sincronização: agora")
        self._refresh_labels()

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

    def _clear_import(self) -> None:
        if self._import_worker is not None:
            self._import_worker.deleteLater()
        if self._import_thread is not None:
            self._import_thread.deleteLater()
        self._import_worker = None
        self._import_thread = None
        self.sync_button.setText("Sincronizar Client.log")
        self.sync_button.setEnabled(True)

    def capture_pull(self, items: Iterable[object]) -> None:
        """Apply one authorized pull result and notify listeners."""
        item_list = list(items)
        if not item_list:
            return
        self.state.resonator = (self.state.resonator or 0) + len(item_list)
        self.state.total_registered += len(item_list)
        self._refresh_labels()
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
            data = bytes(reply.readAll()) if reply.isOpen() else b""
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
            data = bytes(reply.readAll()) if reply.isOpen() else b""
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
        self.manager = NoticeManager()
        self.worker: NoticeLoadWorker | None = None
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
        self._start_notice_load()

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
        for index, image_url in enumerate(self.hero_images):
            reply = self.hero_manager.get(QNetworkRequest(QUrl(image_url)))
            reply.finished.connect(lambda index=index, reply=reply: self._set_hero_image(reply, index))
        root.addWidget(hero)

    def _set_hero_hover(self, hovered: bool) -> None:
        self.btn_prev.setVisible(hovered)
        self.btn_next.setVisible(hovered)
        if hovered:
            self.slide_timer.stop()
        else:
            self.slide_timer.start()

    def _set_hero_image(self, reply: QNetworkReply, index: int) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError and reply.isOpen():
            pixmap = QPixmap()
            data = bytes(reply.readAll()) if reply.isOpen() else b""
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                self.hero_pixmaps[index] = pixmap
                if index == self.hero_index:
                    self._display_hero_pixmap(pixmap)
        reply.deleteLater()

    def _display_hero_pixmap(self, pixmap: QPixmap) -> None:
        self.hero_image.setPixmap(pixmap.scaled(
            self.hero_image.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _change_slide(self, direction: int) -> None:
        if getattr(self, "_slide_group", None) is not None and self._slide_group.state() == QAbstractAnimation.State.Running:
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

    def _start_notice_load(self) -> None:
        self.worker = NewsFetcherWorker(self.manager, self)
        self.worker.news_loaded.connect(self._set_notices)
        self.worker.failed.connect(lambda message: self._set_notices(self.manager.fallback()))
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
        self.hero_pixmaps = [QPixmap() for _ in self.hero_images]
        for index, image_url in enumerate(self.hero_images):
            reply = self.hero_manager.get(QNetworkRequest(QUrl(image_url)))
            reply.finished.connect(lambda index=index, reply=reply: self._set_hero_image(reply, index))
        self._render_notices()

    def _render_notices(self) -> None:
        while self.notice_layout.count() > 1:
            item = self.notice_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        selected = self.tabs.tabText(self.tabs.currentIndex())
        filtered = [
            notice for notice in self.notices
            if str(notice.get("category", "")).casefold() == selected.casefold()
        ]
        for notice in filtered:
            self.notice_layout.insertWidget(self.notice_layout.count() - 1, NoticeRow(notice))

    def _refresh_event_times(self) -> None:
        for index in range(self.notice_layout.count() - 1):
            widget = self.notice_layout.itemAt(index).widget()
            if isinstance(widget, NoticeRow):
                widget.update_remaining(getattr(widget, "end_at", ""))