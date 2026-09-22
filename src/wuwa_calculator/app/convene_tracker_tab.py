"""Dedicated Convene Tracker presentation backed by the existing tracker."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.wuwa_calculator.app.components import Card, TitleLabel
from src.wuwa_calculator.app.pity_tracker import LegacyPityTrackerWidget, TrackerStatus
from src.wuwa_calculator.domain.pity import PityState


class ConveneTrackerTab(QWidget):
    """Present the state owned by the existing LegacyPityTrackerWidget."""

    def __init__(
        self,
        tracker: LegacyPityTrackerWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tracker = tracker
        self.setObjectName("conveneTrackerTab")
        self._build_ui()
        self.tracker.state_changed.connect(self._on_state_changed)
        self.tracker.status_changed.connect(self._on_status_changed)
        self.tracker.history_changed.connect(self._on_history_changed)
        self._on_state_changed(self.tracker.state)
        self._on_status_changed(self.tracker.tracker_status)
        self._on_history_changed(self.tracker.history_records)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QFrame#conveneTrackerPanel { background: rgba(12, 18, 28, 210); "
            "border: 1px solid rgba(111, 180, 220, 55); border-radius: 12px; }"
            "QFrame#conveneTrackerMetric { background: rgba(18, 28, 40, 180); "
            "border: 1px solid rgba(111, 180, 220, 45); border-radius: 10px; }"
            "QFrame#conveneTrackerPanel[guaranteed=\"true\"] { "
            "background: rgba(45, 105, 91, 150); border-color: rgba(110, 225, 178, 150); }"
            "QLabel#conveneTrackerValue { color: #E8F7FF; font-size: 26px; font-weight: 800; }"
            "QLabel#conveneTrackerSummaryValue { color: #E8F7FF; font-size: 20px; font-weight: 800; }"
            "QLabel#conveneTrackerSection { color: #F4F7FF; font-size: 12px; font-weight: 800; }"
            "QLabel#conveneTrackerMuted { color: #9DAFBE; font-size: 10px; }"
            "QLabel#conveneTrackerMetricLabel { color: #D4E8F4; font-size: 10px; font-weight: 700; letter-spacing: 0.4px; }"
            "QLabel#conveneTrackerMetricValue { color: #F3F8FF; font-size: 22px; font-weight: 800; }"
            "QLabel#conveneTrackerInfoValue { color: #EAF7FF; font-size: 15px; font-weight: 800; }"
            "QLabel#conveneTrackerInfoCaption { color: #9DAFBE; font-size: 9px; font-weight: 700; letter-spacing: 0.4px; }"
            "QProgressBar { background: rgba(255,255,255,18); border: 0; border-radius: 3px; }"
            "QProgressBar::chunk { background: #69D6D0; border-radius: 3px; }"
            "QTableWidget#conveneHistoryTable { background: rgba(10, 16, 24, 150); border: 1px solid rgba(111, 180, 220, 26); "
            "gridline-color: rgba(150, 190, 210, 30); color: #DCEAF0; selection-background-color: rgba(96, 165, 250, 80); "
            "selection-color: #E8F7FF; alternate-background-color: rgba(18, 26, 34, 150); }"
            "QHeaderView::section { background: rgba(35, 52, 66, 210); color: #AFC6D2; "
            "border: 0; padding: 6px; font-size: 10px; font-weight: 700; }"
            "QLabel#conveneHistoryEmpty { color: #C7D6E6; font-size: 11px; background: rgba(18, 26, 34, 130); "
            "border: 1px solid rgba(111, 180, 220, 18); border-radius: 8px; padding: 10px; }"
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("conveneTrackerScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)

        header = Card()
        header.setObjectName("conveneTrackerPanel")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 14)
        title_box = QVBoxLayout()
        title_box.addWidget(TitleLabel("Convene Tracker"))
        subtitle = QLabel("Acompanhe seu pity e o histórico de Convene.")
        subtitle.setObjectName("conveneTrackerMuted")
        title_box.addWidget(subtitle)
        self.status_label = QLabel("Pronto")
        self.status_label.setObjectName("conveneTrackerMuted")
        title_box.addWidget(self.status_label)
        self.status_message_label = QLabel("")
        self.status_message_label.setObjectName("conveneTrackerMuted")
        self.status_message_label.setWordWrap(True)
        title_box.addWidget(self.status_message_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        self.refresh_button = QPushButton("Atualizar")
        self.refresh_button.setObjectName("primaryAction")
        self.refresh_button.clicked.connect(self._request_refresh)
        header_layout.addWidget(self.refresh_button)
        root.addWidget(header)

        pity_card = Card()
        pity_card.setObjectName("conveneTrackerPanel")
        pity_layout = QVBoxLayout(pity_card)
        pity_layout.setContentsMargins(16, 14, 16, 14)
        pity_title = QLabel("PITY ATUAL")
        pity_title.setObjectName("conveneTrackerSection")
        pity_layout.addWidget(pity_title)
        self.pity_values: dict[str, QLabel] = {}
        self.pity_bars: dict[str, QProgressBar] = {}
        pity_grid = QGridLayout()
        pity_grid.setHorizontalSpacing(18)
        pity_grid.setVerticalSpacing(10)
        for index, key in enumerate(
            ("resonator", "weapon", "standard_character", "standard_weapon")
        ):
            panel = QFrame()
            panel.setObjectName("conveneTrackerMetric")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(12, 10, 12, 10)
            label = QLabel(self._pool_title(key))
            label.setObjectName("conveneTrackerMetricLabel")
            value = QLabel("-- / 80")
            value.setObjectName("conveneTrackerMetricValue")
            progress = QProgressBar()
            progress.setRange(0, 80)
            progress.setTextVisible(False)
            progress.setFixedHeight(6)
            panel_layout.addWidget(label)
            panel_layout.addWidget(value)
            panel_layout.addWidget(progress)
            pity_grid.addWidget(panel, index // 2, index % 2)
            self.pity_values[key] = value
            self.pity_bars[key] = progress
        pity_layout.addLayout(pity_grid)
        root.addWidget(pity_card)

        status_row = QHBoxLayout()
        status_row.setSpacing(14)
        self.guarantee_card = Card()
        self.guarantee_card.setObjectName("conveneTrackerPanel")
        guarantee_layout = QVBoxLayout(self.guarantee_card)
        guarantee_layout.setContentsMargins(16, 12, 16, 12)
        guarantee_title = QLabel("GARANTIA")
        guarantee_title.setObjectName("conveneTrackerSection")
        guarantee_layout.addWidget(guarantee_title)
        self.guarantee_caption = QLabel("Estado atual")
        self.guarantee_caption.setObjectName("conveneTrackerInfoCaption")
        guarantee_layout.addWidget(self.guarantee_caption)
        self.guarantee_label = QLabel("--")
        self.guarantee_label.setObjectName("conveneTrackerInfoValue")
        guarantee_layout.addWidget(self.guarantee_label)
        status_row.addWidget(self.guarantee_card, 1)

        recent_card = Card()
        recent_card.setObjectName("conveneTrackerPanel")
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(16, 12, 16, 12)
        recent_title = QLabel("ÚLTIMO 5★")
        recent_title.setObjectName("conveneTrackerSection")
        recent_layout.addWidget(recent_title)
        self.last_five_caption = QLabel("Registro mais recente")
        self.last_five_caption.setObjectName("conveneTrackerInfoCaption")
        recent_layout.addWidget(self.last_five_caption)
        self.last_five_label = QLabel("Nenhum 5★ registrado")
        self.last_five_label.setObjectName("conveneTrackerInfoValue")
        self.last_five_label.setWordWrap(True)
        recent_layout.addWidget(self.last_five_label)
        status_row.addWidget(recent_card, 1)
        root.addLayout(status_row)

        summary = Card()
        summary.setObjectName("conveneTrackerPanel")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(16, 10, 16, 10)
        summary_layout.setVerticalSpacing(5)
        summary_title = QLabel("ESTATÍSTICAS")
        summary_title.setObjectName("conveneTrackerSection")
        summary_layout.addWidget(summary_title, 0, 0, 1, 4)
        self.summary_values: dict[str, QLabel] = {}
        for index, (key, title) in enumerate(
            (("total", "Total de pulls"), ("five", "Total de 5★"), ("four", "Total de 4★"))
        ):
            box = QVBoxLayout()
            value = QLabel("--")
            value.setObjectName("conveneTrackerSummaryValue")
            box.addWidget(value)
            label = QLabel(title)
            label.setObjectName("conveneTrackerMuted")
            box.addWidget(label)
            summary_layout.addLayout(box, 1, index)
            self.summary_values[key] = value
        history_summary_title = QLabel("RESUMO DO HISTÓRICO")
        history_summary_title.setObjectName("conveneTrackerSection")
        summary_layout.addWidget(history_summary_title, 2, 0, 1, 4)
        self.history_summary_values = {
            "five": QLabel("★★★★★ 5★ — 0"),
            "four": QLabel("★★★★ 4★ — 0"),
            "three": QLabel("★★★ 3★ — 0"),
            "latest": QLabel("Último registro: Nenhum registro disponível"),
            "period": QLabel("Período indisponível"),
        }
        for column, key in enumerate(("five", "four", "three")):
            label = self.history_summary_values[key]
            label.setObjectName("conveneTrackerMuted")
            summary_layout.addWidget(label, 3, column)
        self.history_summary_values["latest"].setObjectName("conveneTrackerMuted")
        self.history_summary_values["period"].setObjectName("conveneTrackerMuted")
        summary_layout.addWidget(self.history_summary_values["latest"], 4, 0, 1, 4)
        summary_layout.addWidget(self.history_summary_values["period"], 5, 0, 1, 4)
        root.addWidget(summary)

        history_card = Card()
        history_card.setObjectName("conveneTrackerPanel")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(16, 12, 16, 12)
        history_title = QLabel("HISTÓRICO RECENTE")
        history_title.setObjectName("conveneTrackerSection")
        history_layout.addWidget(history_title)
        self.history_table = QTableWidget(0, 4)
        self.history_table.setObjectName("conveneHistoryTable")
        self.history_table.setHorizontalHeaderLabels(("Raridade", "Item", "Pool", "Data"))
        self.history_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setWordWrap(False)
        self.history_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_table.setShowGrid(True)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(0)
        self.history_table.setColumnWidth(0, 76)
        self.history_table.setColumnWidth(2, 120)
        self.history_table.setColumnWidth(3, 132)
        self.history_empty_label = QLabel("Nenhum registro de Convene disponível.")
        self.history_empty_label.setObjectName("conveneHistoryEmpty")
        self.history_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        history_layout.addWidget(self.history_table, 1)
        history_layout.addWidget(self.history_empty_label, 1)
        root.addWidget(history_card, 1)

    @staticmethod
    def _pool_title(pool: str) -> str:
        return {
            "resonator": "Resonator Convene",
            "weapon": "Weapon Convene",
            "standard_character": "Standard Character",
            "standard_weapon": "Standard Weapon",
        }.get(pool, pool)

    def _request_refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.tracker.request_sync()

    def _on_state_changed(self, state: PityState) -> None:
        for key, label in self.pity_values.items():
            value = getattr(state, key, None)
            label.setText(f"{value if value is not None else '--'} / 80")
            bounded_value = max(0, min(80, value or 0))
            self.pity_bars[key].setValue(bounded_value)
            self.pity_bars[key].setStyleSheet(
                "QProgressBar { background: rgba(255,255,255,18); border: 0; border-radius: 3px; }"
                f"QProgressBar::chunk {{ background: {self._pity_color(bounded_value)}; border-radius: 3px; }}"
            )
        guarantee = (
            "Sim" if state.guaranteed is True
            else "Não" if state.guaranteed is False
            else "--"
        )
        self.guarantee_label.setText(guarantee)
        self.guarantee_card.setProperty("guaranteed", state.guaranteed is True)
        self.guarantee_card.style().unpolish(self.guarantee_card)
        self.guarantee_card.style().polish(self.guarantee_card)
        recent = state.recent_convene_details[-1] if state.recent_convene_details else None
        self.last_five_label.setText(recent if recent else "Nenhum 5★ registrado")
        self.summary_values["total"].setText(str(state.total_registered))
        self.summary_values["five"].setText(str(len(state.five_star_history)))
        self.summary_values["four"].setText(str(state.four_star_total))

        self._update_latest_five_label()
        self._update_history_summary()

    @staticmethod
    def _pity_color(value: int) -> str:
        if value >= 65:
            return "#F2B36B"
        if value >= 40:
            return "#D7C56A"
        return "#69D6D0"

    def _on_status_changed(self, status: TrackerStatus) -> None:
        if status.last_sync_at:
            stamp = status.last_sync_at.replace("T", " ")
            self.status_label.setText(f"Última sincronização: {stamp}")
        else:
            self.status_label.setText("Última sincronização: --")

        message = {
            "running": "Sincronização em andamento...",
            "success": "✓ Sincronização concluída",
            "success_no_new": "✓ Sincronização concluída",
            "error": "Não foi possível sincronizar o histórico.",
            "offline": "Não foi possível conectar ao serviço.",
        }.get(status.sync_status, "Sincronização")
        self.status_message_label.setText(message)
        self.refresh_button.setEnabled(status.sync_status not in {"running"})

    def _on_history_changed(self, records: list[dict[str, object]]) -> None:
        valid_records = [record for record in records if isinstance(record, dict)]
        self.history_empty_label.setVisible(not valid_records)
        self.history_table.setVisible(bool(valid_records))
        self.history_table.setRowCount(len(valid_records))
        for row, record in enumerate(reversed(valid_records)):
            rarity_value = self._first_value(record, "rarity", "quality", "rank")
            rarity_text = self._format_rarity(rarity_value)
            values = (
                rarity_text,
                self._first_value(record, "name", "item", "title") or "Desconhecido",
                self._format_pool(self._first_value(record, "pool", "type", "gacha_type")),
                self._format_timestamp(self._first_value(record, "timestamp", "time", "date")),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setForeground(QColor(self._rarity_color(rarity_value)))
                self.history_table.setItem(row, column, item)

        self._update_latest_five_label()
        self._update_history_summary()

    def _update_latest_five_label(self) -> None:
        latest_five = next(
            (
                record for record in reversed(self.tracker.history_records)
                if isinstance(record, dict)
                and self._first_value(record, "rarity", "quality", "rank") == "5"
            ),
            None,
        )
        if latest_five is None:
            self.last_five_label.setText("Nenhum 5★ registrado")
            return
        item = self._first_value(latest_five, "name", "item", "title") or "Desconhecido"
        pool = self._format_pool(self._first_value(latest_five, "pool", "type", "gacha_type"))
        date = self._format_timestamp(
            self._first_value(latest_five, "timestamp", "time", "date")
        )
        self.last_five_label.setText(f"Último 5★: {item} · {pool} · {date}")

    def _update_history_summary(self) -> None:
        records = [record for record in self.tracker.history_records if isinstance(record, dict)]
        counts = {"3": 0, "4": 0, "5": 0}
        for record in records:
            rarity = self._first_value(record, "rarity", "quality", "rank")
            if rarity in counts:
                counts[rarity] += 1
        self.history_summary_values["five"].setText(f"★★★★★ 5★ — {counts['5']}")
        self.history_summary_values["four"].setText(f"★★★★ 4★ — {counts['4']}")
        self.history_summary_values["three"].setText(f"★★★ 3★ — {counts['3']}")

        if records:
            latest = records[-1]
            item = self._first_value(latest, "name", "item", "title") or "Desconhecido"
            pool = self._format_pool(self._first_value(latest, "pool", "type", "gacha_type"))
            date = self._format_timestamp(
                self._first_value(latest, "timestamp", "time", "date")
            )
            rarity = self._format_rarity(
                self._first_value(latest, "rarity", "quality", "rank")
            )
            self.history_summary_values["latest"].setText(
                f"Último registro: {rarity} · {item} · {pool} · {date}"
            )
        else:
            self.history_summary_values["latest"].setText(
                "Último registro: Nenhum registro disponível"
            )

        parsed_dates = [
            parsed for record in records
            if (parsed := self._parse_timestamp_value(
                self._first_value(record, "timestamp", "time", "date")
            )) is not None
        ]
        if parsed_dates:
            first = min(parsed_dates).strftime("%d/%m/%Y %H:%M")
            last = max(parsed_dates).strftime("%d/%m/%Y %H:%M")
            self.history_summary_values["period"].setText(
                f"Período: {first} → {last}"
            )
        else:
            self.history_summary_values["period"].setText("Período indisponível")

    @staticmethod
    def _first_value(record: dict[str, object], *keys: str) -> str:
        for key in keys:
            value = record.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    @staticmethod
    def _format_rarity(value: str) -> str:
        try:
            rarity = int(value)
        except (TypeError, ValueError):
            return "--" if not value else value
        if rarity in (3, 4, 5):
            return "★" * rarity
        return str(rarity)

    @staticmethod
    def _rarity_color(value: str) -> str:
        return {"5": "#F2D47A", "4": "#C49BFF", "3": "#8FC9E8"}.get(value, "#DCEAF0")

    @staticmethod
    def _format_pool(value: str) -> str:
        if not value:
            return "--"
        return {
            "resonator": "Resonator",
            "weapon": "Weapon",
        }.get(value.casefold(), value.replace("_", " ").strip().title())

    @staticmethod
    def _parse_timestamp_value(value: str) -> datetime | None:
        if not value:
            return None
        try:
            if value.replace(".", "", 1).isdigit():
                return datetime.fromtimestamp(float(value), timezone.utc)
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None

    @staticmethod
    def _format_timestamp(value: str) -> str:
        if not value:
            return "--"
        try:
            if value.replace(".", "", 1).isdigit():
                parsed = datetime.fromtimestamp(float(value), timezone.utc)
            else:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            return value

