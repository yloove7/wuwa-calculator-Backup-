"""Player nativo QtMultimedia para a tela de histórico de rotações.

English: Native QtMultimedia player for the rotation history screen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QRect,
    QSignalBlocker,
    QTimer,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QImage,
    QKeyEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

# Allow direct execution from the app/ directory while keeping package imports
# as the canonical path used by the Tethys launcher.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.wuwa_calculator.app.components import Card, TitleLabel


class LivePreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = QImage()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._repaint_latest_frame)
        self.setMinimumSize(1, 1)

    def set_frame(self, image: QImage) -> None:
        if image.isNull():
            return
        self._image = image
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(max(1, round(1000.0 / 60.0)))

    def _repaint_latest_frame(self) -> None:
        self.update()

    def clear_frame(self) -> None:
        self._image = QImage()
        self.update()

    def pixmap(self) -> QPixmap:
        return QPixmap.fromImage(self._image)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._image.isNull():
            target = self._image.size()
            target.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - target.width()) // 2
            y = (self.height() - target.height()) // 2
            painter.drawImage(QRect(x, y, target.width(), target.height()), self._image)
        painter.end()


class ClickableSeekSlider(QSlider):
    """Barra de busca com suporte a arraste e clique direto na posição.

    English: Seek bar that supports both dragging and direct position clicks.
    """

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
        smooth_drag: bool = False,
    ) -> None:
        super().__init__(orientation, parent)
        self._smooth_drag = smooth_drag
        self._mouse_drag_active = False
        self._drag_handle_offset = 0.0
        self._drag_start_handle_center = 0.0
        self._drag_start_value = self.minimum()

    def mousePressEvent(self, event) -> None:
        if (
            not self._smooth_drag
            and event.button() == Qt.MouseButton.LeftButton
            and self.maximum() > self.minimum()
        ):
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                round(event.position().x()),
                max(1, self.width()),
            )
            self.sliderPressed.emit()
            self.setValue(value)
            self.sliderMoved.emit(value)
            self.sliderReleased.emit()
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.maximum() > self.minimum()
            and self.orientation() == Qt.Orientation.Horizontal
        ):
            handle = self._handle_rect()
            mouse_x = event.position().x()
            if handle.contains(round(mouse_x), round(event.position().y())):
                self._mouse_drag_active = True
                self._drag_handle_offset = mouse_x - handle.center().x()
                self._drag_start_handle_center = float(handle.center().x())
                self._drag_start_value = self.value()
                self.setSliderDown(True)
            else:
                value = self._value_at_mouse_x(mouse_x)
                self.setValue(value)
                self.sliderMoved.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._mouse_drag_active:
            value = self._value_during_drag(event.position().x())
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._mouse_drag_active and event.button() == Qt.MouseButton.LeftButton:
            value = self._value_during_drag(event.position().x())
            self.setValue(value)
            self._mouse_drag_active = False
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _handle_rect(self) -> QRect:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )

    def _value_at_mouse_x(self, mouse_x: float) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = self._handle_rect()
        minimum_center = groove.left() + handle.width() // 2
        maximum_center = groove.right() - handle.width() // 2
        span = max(0, maximum_center - minimum_center)
        position = round(mouse_x - minimum_center)
        position = max(0, min(span, position))
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), position, span, option.upsideDown
        )

    def _value_during_drag(self, mouse_x: float) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = self._handle_rect()
        minimum_center = groove.left() + handle.width() // 2
        maximum_center = groove.right() - handle.width() // 2
        span = max(1, maximum_center - minimum_center)
        current_center = mouse_x - self._drag_handle_offset
        delta = round(
            (self.maximum() - self.minimum())
            * (current_center - self._drag_start_handle_center)
            / span
        )
        if option.upsideDown:
            delta = -delta
        return max(self.minimum(), min(self.maximum(), self._drag_start_value + delta))


class HistoryVideoPlayer(Card):
    """Player local incorporável baseado exclusivamente em QtMultimedia.

    English: Embeddable local player backed exclusively by QtMultimedia.
    """

    videoLoaded = Signal(str)
    videoStopped = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("mediaPlayer", True)
        self.video_path = ""
        self.duration_ms = 0
        self.is_dragging = False
        self._source_ready = False
        self._is_fullscreen = False
        self._is_seeking = False
        self._last_display_second = -1
        self._live_capture_mode = False

        self.media_player = QMediaPlayer(self)
        self._audio_output: QAudioOutput | None = None
        self._pending_volume = 1.0
        self._pending_muted = False

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = TitleLabel("Wuthering Waves")
        self.title_label.setObjectName("mediaPlayerTitle")
        header.addWidget(self.title_label)
        self.status_label = QLabel("PRONTO")
        self.status_label.setObjectName("mediaStatusBadge")
        header.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        self._video_widget: QVideoWidget | None = None
        self._fullscreen_stack_index: int | None = None
        self._video_placeholder = QFrame(self)
        self._video_placeholder.setObjectName("videoSurface")
        self._video_placeholder.setMinimumSize(1, 1)
        self.live_preview = LivePreviewWidget(self)
        self.live_preview.setObjectName("liveCapturePreview")
        self.live_preview.hide()
        self.video_stack = QStackedWidget(self)
        self.video_stack.setObjectName("videoPreviewStack")
        self.video_stack.addWidget(self._video_placeholder)
        self.video_stack.addWidget(self.live_preview)
        self.hud_label = QLabel("LIVE ANALYZER  //  60 FPS", self._video_placeholder)
        self.hud_label.setObjectName("videoHud")
        self.hud_label.setFixedHeight(26)
        self._position_video_hud()
        self.hud_label.raise_()
        layout.addWidget(self.video_stack, 1)

        toolbar = QFrame()
        toolbar.setObjectName("mediaToolbar")
        self.media_toolbar = toolbar
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(8, 5, 8, 5)
        controls.setSpacing(7)
        self.progress_slider = ClickableSeekSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setObjectName("playerProgress")
        self.progress_slider.setRange(0, 0)
        self.browse_button = self._button("▣  Selecionar vídeo")
        self.browse_button.setObjectName("mediaBrowseButton")
        self.browse_button.setText("▣")
        self.browse_button.setToolTip("Selecionar vídeo")
        self.browse_button.setFixedWidth(38)
        self.play_button = self._button("▶  Play")
        self.play_button.setObjectName("mediaPlayButton")
        self.play_button.setText("▶")
        self.play_button.setToolTip("Reproduzir ou pausar")
        self.play_button.setFixedWidth(42)
        self.stop_button = self._button("■  Parar")
        self.stop_button.setObjectName("mediaStopButton")
        self.stop_button.setText("■")
        self.stop_button.setToolTip("Parar vídeo")
        self.stop_button.setFixedWidth(42)
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        controls.addWidget(self.browse_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.progress_slider, 1)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("mediaTimeLabel")
        self.time_label.setFixedWidth(82)
        controls.addWidget(self.time_label)
        controls.addStretch(1)

        volume_label = QLabel("Volume")
        volume_label.setObjectName("mediaControlLabel")
        controls.addWidget(volume_label)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("playerVolume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(60)
        controls.addWidget(self.volume_slider)

        self.subtitle_box = QComboBox()
        self.subtitle_box.setObjectName("mediaSubtitleBox")
        self.subtitle_box.setToolTip("Legendas")
        self.subtitle_box.setFixedWidth(90)
        self.subtitle_box.addItem("Legendas desativadas", -1)
        controls.addWidget(self.subtitle_box)
        self.fullscreen_button = self._button("⛶")
        self.fullscreen_button.setToolTip("Tela cheia")
        self.fullscreen_button.setFixedWidth(38)
        self.fullscreen_button.setEnabled(False)
        controls.addWidget(self.fullscreen_button)
        layout.addWidget(toolbar)

    def _position_video_hud(self) -> None:
        self.hud_label.move(12, 12)

    @property
    def video_surface(self) -> QVideoWidget:
        """Return the native video surface, creating it on explicit use."""
        return self._ensure_video_widget()

    def _ensure_video_widget(self) -> QVideoWidget:
        if self._video_widget is not None:
            return self._video_widget
        video_widget = QVideoWidget(self)
        video_widget.setObjectName("videoSurface")
        self._video_widget = video_widget
        self._configure_video_surface()
        video_widget.fullScreenChanged.connect(self._on_video_fullscreen_changed)
        video_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.media_player.setVideoOutput(video_widget)
        video_widget.installEventFilter(self)
        self.video_stack.insertWidget(0, video_widget)
        self.video_stack.removeWidget(self._video_placeholder)
        self.video_stack.setCurrentWidget(video_widget)
        self._video_placeholder.hide()
        self._video_placeholder.deleteLater()
        self.hud_label.setParent(video_widget)
        self.hud_label.raise_()
        self.hud_label.setVisible(not self._live_capture_mode and not self._is_fullscreen)
        self._position_video_hud()
        return video_widget

    @property
    def audio_output(self) -> QAudioOutput:
        """Return the audio output, creating it for explicit public access."""
        return self._ensure_audio_output()

    def _ensure_audio_output(self) -> QAudioOutput:
        if self._audio_output is not None:
            return self._audio_output
        audio_output = QAudioOutput(self)
        audio_output.setVolume(self._pending_volume)
        audio_output.setMuted(self._pending_muted)
        self.media_player.setAudioOutput(audio_output)
        self._audio_output = audio_output
        return audio_output

    def set_muted(self, muted: bool) -> None:
        self._pending_muted = bool(muted)
        if self._audio_output is not None:
            self._audio_output.setMuted(self._pending_muted)

    def set_live_capture_mode(self, enabled: bool) -> None:
        self._live_capture_mode = enabled
        self.media_toolbar.setVisible(not enabled)
        self.hud_label.setVisible(not enabled and not self._is_fullscreen)
        self.video_stack.setCurrentWidget(
            self.live_preview if enabled else (self._video_widget or self._video_placeholder)
        )
        self.live_preview.setVisible(enabled)
        if enabled:
            self.media_player.pause()
        else:
            self.live_preview.clear_frame()

    def set_live_game_title(self, title: str) -> None:
        self.title_label.setText(title.strip() or "Jogo detectado")

    def set_live_preview(self, image: QImage) -> None:
        if image.isNull():
            return
        self.live_preview.set_frame(image)

    def _configure_video_surface(self) -> None:
        if self._video_widget is None:
            return
        self._video_widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._video_widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self._video_widget.setAutoFillBackground(False)
        self._video_widget.setUpdatesEnabled(True)
        self._video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, False)

    def _refresh_video_surface(self) -> None:
        if self._video_widget is not None:
            self._video_widget.update()
            self._video_widget.repaint()

    @staticmethod
    def _button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("mediaControlButton")
        return button

    def _connect_signals(self) -> None:
        self.browse_button.clicked.connect(self.choose_video)
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button.clicked.connect(self.stop_video)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.progress_slider.sliderPressed.connect(self._begin_seek)
        self.progress_slider.sliderMoved.connect(self._preview_seek)
        self.progress_slider.sliderReleased.connect(self._commit_seek)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.media_player.errorOccurred.connect(self._on_error)
        self.media_player.tracksChanged.connect(self._populate_subtitles)
        self.subtitle_box.currentIndexChanged.connect(self._select_subtitle)
        self.fullscreen_button.clicked.connect(self.enter_fullscreen)

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar vídeo de referência",
            "",
            "Vídeos (*.mp4 *.mkv *.avi *.mov *.webm);;Todos os arquivos (*)",
        )
        if path:
            self.load_video(path)

    def load_video(self, path: str) -> bool:
        if not os.path.isfile(path):
            self._set_status("Arquivo de vídeo não encontrado")
            return False
        self.stop_video()
        self.media_player.setVideoOutput(self._ensure_video_widget())
        self.video_path = str(Path(path).resolve())
        self._source_ready = False
        self.title_label.setText(Path(path).name)
        self._set_status(f"Carregando: {Path(path).name}")
        self._set_controls_enabled(True)
        self.media_player.setSource(QUrl.fromLocalFile(self.video_path))
        self.videoLoaded.emit(self.video_path)
        self._ensure_audio_output()
        self.media_player.play()
        QTimer.singleShot(0, self._refresh_video_surface)
        return True

    def toggle_playback(self) -> None:
        if not self.video_path:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self._ensure_audio_output()
            self.media_player.play()

    def stop_video(self) -> None:
        self.exit_fullscreen()
        self._source_ready = False
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self.video_path = ""
        self.title_label.setText("Wuthering Waves")
        self.duration_ms = 0
        self.is_dragging = False
        self._is_seeking = False
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setValue(0)
        self.time_label.setText("0:00 / 0:00")
        self.play_button.setText("▶")
        self._set_status("PRONTO")
        self._set_controls_enabled(False)
        self._reset_subtitles()
        self.videoStopped.emit()

    def enter_fullscreen(self) -> None:
        video_widget = self._video_widget
        if video_widget is None:
            return
        if video_widget.isFullScreen():
            if not self._is_fullscreen:
                self._on_video_fullscreen_changed(True)
            video_widget.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        stack_index = self.video_stack.indexOf(video_widget)
        if stack_index >= 0:
            self._fullscreen_stack_index = stack_index
            self.video_stack.removeWidget(video_widget)
        video_widget.setFullScreen(True)
        is_fullscreen = video_widget.isFullScreen()
        if is_fullscreen != self._is_fullscreen:
            self._on_video_fullscreen_changed(is_fullscreen)
        if is_fullscreen:
            video_widget.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self._restore_video_widget_to_stack()

    def exit_fullscreen(self) -> None:
        video_widget = self._video_widget
        if video_widget is None:
            return
        if not video_widget.isFullScreen():
            if self._is_fullscreen:
                self._on_video_fullscreen_changed(False)
            return
        video_widget.setFullScreen(False)
        is_fullscreen = video_widget.isFullScreen()
        if is_fullscreen != self._is_fullscreen:
            self._on_video_fullscreen_changed(is_fullscreen)

    def _on_video_fullscreen_changed(self, _signal_state: bool) -> None:
        video_widget = self._video_widget
        if video_widget is None:
            return
        is_fullscreen = video_widget.isFullScreen()
        self._is_fullscreen = is_fullscreen
        self.hud_label.setVisible(not is_fullscreen and not self._live_capture_mode)
        if is_fullscreen:
            return
        QTimer.singleShot(0, self._refresh_video_surface)
        QTimer.singleShot(0, self._restore_video_widget_to_stack)

    def _restore_video_widget_to_stack(self) -> None:
        video_widget = self._video_widget
        stack_index = self._fullscreen_stack_index
        if (
            video_widget is None
            or stack_index is None
            or video_widget.isFullScreen()
        ):
            return
        if self.video_stack.indexOf(video_widget) < 0:
            self.video_stack.insertWidget(stack_index, video_widget)
        self.video_stack.setCurrentWidget(video_widget)
        self._fullscreen_stack_index = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        video_widget = self._video_widget
        if video_widget is not None and watched is video_widget and video_widget.isFullScreen():
            if (
                isinstance(event, QKeyEvent)
                and event.key() == Qt.Key.Key_Space
            ):
                if (
                    event.type() == QEvent.Type.KeyPress
                    and not event.isAutoRepeat()
                ):
                    self.toggle_playback()
                event.accept()
                return True
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self.exit_fullscreen()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def set_volume(self, value: int) -> None:
        self._pending_volume = max(0, min(100, int(value))) / 100.0
        if self._audio_output is not None:
            self._audio_output.setVolume(self._pending_volume)

    def _begin_seek(self) -> None:
        self._is_seeking = True
        self.is_dragging = True

    def _preview_seek(self, value: int) -> None:
        value = max(0, min(self.duration_ms, int(value)))
        display_time = f"{self._clock(value)} / {self._clock(self.duration_ms)}"
        self.time_label.setText(display_time)
        if self.progress_slider.value() != value:
            with QSignalBlocker(self.progress_slider):
                self.progress_slider.setValue(value)
        if not self._is_seeking and self.duration_ms > 0:
            self.media_player.setPosition(value)

    def _commit_seek(self) -> None:
        value = max(0, min(self.duration_ms, self.progress_slider.value()))
        if self.duration_ms > 0:
            self._preview_seek(value)
            self.media_player.setPosition(value)
        self._is_seeking = False
        self.is_dragging = False

    def seek_to_seconds(self, seconds: float) -> None:
        """Seek the loaded video to a timestamp supplied by an external control."""
        if self.duration_ms <= 0:
            return
        position_ms = max(0, min(self.duration_ms, round(float(seconds) * 1000)))
        self.media_player.setPosition(position_ms)

    def _on_position_changed(self, position_ms: int) -> None:
        if (
            not self._source_ready
            or not self.video_path
            or self.duration_ms <= 0
            or self._is_seeking
        ):
            return
        self.progress_slider.setValue(position_ms)
        display_second = position_ms // 1000
        if display_second != self._last_display_second:
            display_time = f"{self._clock(position_ms)} / {self._clock(self.duration_ms)}"
            self.time_label.setText(display_time)
            self._last_display_second = display_second

    def _on_duration_changed(self, duration_ms: int) -> None:
        self.duration_ms = max(0, int(duration_ms))
        self._source_ready = self.duration_ms > 0 and bool(self.video_path)
        self.progress_slider.setRange(0, self.duration_ms)
        self.time_label.setText(f"{self._clock(self.media_player.position())} / {self._clock(self.duration_ms)}")
        self._last_display_second = self.media_player.position() // 1000

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused = state == QMediaPlayer.PlaybackState.PausedState
        self.play_button.setText("Ⅱ" if playing else "▶")
        if paused:
            self._set_status("Pausado")
        elif playing:
            self._set_status("Reproduzindo")

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
        }:
            QTimer.singleShot(0, self._refresh_video_surface)
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_button.setText("▶")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._set_status("Arquivo de mídia inválido")

    def _on_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        self._set_status(message or "Falha ao reproduzir mídia")

    def _populate_subtitles(self) -> None:
        tracks = self.media_player.subtitleTracks()
        with QSignalBlocker(self.subtitle_box):
            self.subtitle_box.clear()
            self.subtitle_box.addItem("Legendas desativadas", -1)
            for index, track in enumerate(tracks):
                description = track.stringValue(track.Key.Title) or f"Legenda {index + 1}"
                self.subtitle_box.addItem(description, index)

    def _select_subtitle(self, index: int) -> None:
        track_index = self.subtitle_box.itemData(index)
        if track_index is not None:
            self.media_player.setActiveSubtitleTrack(int(track_index))

    def _reset_subtitles(self) -> None:
        with QSignalBlocker(self.subtitle_box):
            self.subtitle_box.clear()
            self.subtitle_box.addItem("Legendas desativadas", -1)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.play_button.setEnabled(enabled)
        self.stop_button.setEnabled(enabled)
        self.fullscreen_button.setEnabled(enabled)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    @staticmethod
    def _clock(milliseconds: int) -> str:
        total = max(0, int(milliseconds / 1000))
        return f"{total // 60}:{total % 60:02d}"

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_video_hud()
        QTimer.singleShot(0, self._refresh_video_surface)

    def closeEvent(self, event) -> None:
        self.exit_fullscreen()
        self.stop_video()
        super().closeEvent(event)
