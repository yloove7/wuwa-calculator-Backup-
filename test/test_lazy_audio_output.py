from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication

from src.wuwa_calculator.app.multimedia import history_video_player as player_module

_APPLICATION = QApplication.instance() or QApplication([])


def test_audio_output_is_lazy_and_retains_pending_volume_and_mute(
    monkeypatch,
) -> None:
    created: list[QAudioOutput] = []

    class CountingAudioOutput(QAudioOutput):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            created.append(self)

    monkeypatch.setattr(player_module, "QAudioOutput", CountingAudioOutput)
    player = player_module.HistoryVideoPlayer()

    assert isinstance(player.media_player, QMediaPlayer)
    assert player._audio_output is None
    player.set_volume(35)
    player.set_muted(True)
    assert player._audio_output is None
    assert created == []

    output = player.audio_output

    assert output is player.audio_output
    assert created == [output]
    assert player.media_player.audioOutput() is output
    assert output.volume() == pytest.approx(0.35)
    assert output.isMuted()

    player.set_volume(60)
    player.set_muted(False)
    assert output.volume() == pytest.approx(0.6)
    assert not output.isMuted()
    player.close()


def test_loading_and_replaying_reuse_single_audio_output(
    monkeypatch,
    tmp_path,
) -> None:
    created: list[QAudioOutput] = []

    class CountingAudioOutput(QAudioOutput):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            created.append(self)

    monkeypatch.setattr(player_module, "QAudioOutput", CountingAudioOutput)
    player = player_module.HistoryVideoPlayer()
    player.set_volume(42)
    video_file = tmp_path / "local-video.mp4"
    video_file.write_bytes(b"local test fixture")
    play_calls: list[bool] = []
    state = [QMediaPlayer.PlaybackState.StoppedState]

    def record_play() -> None:
        play_calls.append(True)
        state[0] = QMediaPlayer.PlaybackState.PlayingState

    player.media_player.play = record_play
    player.media_player.pause = lambda: state.__setitem__(
        0, QMediaPlayer.PlaybackState.PausedState
    )
    player.media_player.playbackState = lambda: state[0]
    set_audio_output = player.media_player.setAudioOutput
    attached: list[QAudioOutput] = []

    def record_audio_output(output: QAudioOutput) -> None:
        attached.append(output)
        set_audio_output(output)

    player.media_player.setAudioOutput = record_audio_output

    assert player._audio_output is None
    assert player.load_video(str(video_file))
    output = player._audio_output
    assert output is not None
    assert output.volume() == pytest.approx(0.42)
    assert attached == [output]

    player.toggle_playback()
    player.toggle_playback()
    player.toggle_playback()

    assert len(created) == 1
    assert attached == [output]
    assert len(play_calls) == 2
    assert player._audio_output is output
    player.close()


def test_cleanup_without_audio_output_does_not_create_one(monkeypatch) -> None:
    created: list[QAudioOutput] = []

    class CountingAudioOutput(QAudioOutput):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            created.append(self)

    monkeypatch.setattr(player_module, "QAudioOutput", CountingAudioOutput)
    player = player_module.HistoryVideoPlayer()

    player.close()

    assert player._audio_output is None
    assert created == []
