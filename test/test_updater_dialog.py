import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import updater_dialog
from updater_dialog import (
    DialogoAtualizacao,
    DialogoEstadoAtualizacao,
    DialogoVerificandoAtualizacao,
)

_APPLICATION = QApplication.instance() or QApplication([])


def test_checking_dialog_shows_tethys_message_and_indeterminate_progress() -> None:
    dialog = DialogoVerificandoAtualizacao()

    assert dialog.windowTitle() == "Atualização do Tethys"
    message = dialog.findChild(QLabel, "updaterMessage")
    assert message is not None
    assert message.text() == (
        "Verificando se há uma nova versão…"
    )
    progress = dialog.findChild(QProgressBar, "updaterProgress")
    assert progress is not None
    assert (progress.minimum(), progress.maximum()) == (0, 0)


def test_update_dialog_preserves_later_and_update_actions_and_release_notes() -> None:
    dialog = DialogoAtualizacao(3, "• Primeiro commit\n• Segundo commit")
    assert dialog.windowTitle() == "Nova versão disponível"
    assert dialog.txt_changes.toPlainText() == "• Primeiro commit\n• Segundo commit"
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "v1.4.0" in labels
    assert any("3 commits pendentes" in text for text in labels)

    later = next(
        button for button in dialog.findChildren(QPushButton)
        if button.text() == "Mais tarde"
    )
    later.click()
    assert not dialog.deve_atualizar

    update_dialog = DialogoAtualizacao(1, "• Atualização")
    update_now = next(
        button for button in update_dialog.findChildren(QPushButton)
        if button.text() == "Atualizar agora"
    )
    update_now.click()
    assert update_dialog.deve_atualizar


def test_update_dialog_has_compact_scrollable_changelog_and_repository_link(
    monkeypatch,
) -> None:
    opened_urls: list[str] = []
    monkeypatch.setattr(updater_dialog.webbrowser, "open", opened_urls.append)
    changes = "\n".join(f"• Commit {index}" for index in range(1, 101))
    dialog = DialogoAtualizacao(100, changes)
    dialog.show()
    _APPLICATION.processEvents()
    original_size = (dialog.width(), dialog.height())
    panel = dialog.findChild(QTextEdit, "updaterChanges")
    assert panel is not None
    assert panel.maximumHeight() <= 140
    assert panel.toPlainText() == changes
    assert panel.verticalScrollBar().maximum() > 0

    summary = dialog.findChild(QLabel, "updaterCommitCount")
    assert summary is not None
    assert "+95 outras alterações" in summary.text()
    repository_button = next(
        button for button in dialog.findChildren(QPushButton)
        if button.objectName() == "updaterRepository"
    )
    assert repository_button.text() == "🌐 Ver repositório"
    repository_button.click()

    assert opened_urls == [updater_dialog.GITHUB_RELEASES_URL]
    assert (dialog.width(), dialog.height()) == original_size == (560, 520)


def test_status_dialog_displays_install_and_technical_error_details() -> None:
    installing = DialogoEstadoAtualizacao(
        "Instalando atualização…",
        "Não feche o Tethys enquanto a atualização está sendo instalada.",
        busy=True,
        button_text="",
    )
    assert installing.findChild(QProgressBar, "updaterProgress") is not None

    failed = DialogoEstadoAtualizacao(
        "Não foi possível concluir a atualização.",
        "O Tethys não conseguiu instalar a atualização.",
        technical_details="git pull exited with status 1",
    )
    details = failed.findChild(QTextEdit, "updaterChanges")
    assert details is not None
    assert details.toPlainText() == "git pull exited with status 1"


def test_simulation_opens_fake_update_without_calling_update_mechanisms(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulate-update"])
    dialogs: list[DialogoAtualizacao] = []

    def capture_dialog(dialog: DialogoAtualizacao) -> int:
        dialogs.append(dialog)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(DialogoAtualizacao, "exec", capture_dialog)
    forbidden = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("simulation called the real update flow")
    )
    for name in (
        "_run_git",
        "_fetch_latest_release",
        "_download_release_asset",
        "_check_release_update",
        "obter_info_commits_pendentes",
        "detect_update_mode",
        "_consume_update_applied_signal",
    ):
        monkeypatch.setattr(updater_dialog, name, forbidden)

    assert updater_dialog.executar_verificacao_e_update() is False
    assert sys.argv == ["main.py"]
    assert len(dialogs) == 1
    dialog = dialogs[0]
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "v1.4.2" in labels
    assert "v1.5.0" in labels
    assert "7 commits pendentes" in labels
    assert dialog.simulated
    assert dialog.txt_changes.toPlainText() == updater_dialog._SIMULATED_UPDATE_NOTES
    for note in (
        "Nova interface do Convene Tracker",
        "Melhorias no Auto Update",
        "Correções de estabilidade",
        "Melhorias de desempenho",
        "Ajustes visuais do Tethys",
    ):
        assert note in dialog.txt_changes.toPlainText()


def test_simulated_update_button_only_shows_simulation_notice(monkeypatch) -> None:
    notices: list[tuple[object, str, str]] = []

    def record_notice(parent: object, title: str, message: str) -> None:
        notices.append((parent, title, message))

    monkeypatch.setattr(updater_dialog.QMessageBox, "information", record_notice)
    forbidden = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("simulated button called the real update flow")
    )
    monkeypatch.setattr(updater_dialog, "_run_git", forbidden)
    monkeypatch.setattr(updater_dialog.os, "execv", forbidden)
    dialog = DialogoAtualizacao(
        7,
        updater_dialog._SIMULATED_UPDATE_NOTES,
        current_version="v1.4.2",
        new_version="v1.5.0",
        simulated=True,
    )
    update_now = next(
        button for button in dialog.findChildren(QPushButton)
        if button.text() == "Atualizar agora"
    )

    update_now.click()

    assert notices == [(
        dialog,
        "Simulação do Auto Update",
        "Simulação: a atualização seria iniciada aqui.",
    )]
    assert not dialog.deve_atualizar


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main(["-q", __file__]))
