"""Graphical updater prompt for the Tethys launcher."""

import json
import os
import re
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from version import APP_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parent
AUTO_UPDATE_APPLIED_ENV = "TETHYS_UPDATE_APPLIED"
PENDING_RELEASE_PATH_ENV = "TETHYS_PENDING_RELEASE_PATH"
PENDING_RELEASE_VERSION_ENV = "TETHYS_PENDING_RELEASE_VERSION"
_AUTO_UPDATE_CHECK_RAN = False
SIMULATE_UPDATE_FLAG = "--simulate-update"
_SIMULATED_UPDATE_NOTES = "\n".join((
    "- Nova interface do Convene Tracker",
    "- Melhorias no Auto Update",
    "- Correções de estabilidade",
    "- Melhorias de desempenho",
    "- Ajustes visuais do Tethys",
))
GITHUB_RELEASES_URL = "https://github.com/yloove7/wuwa-calculator-Backup-/releases"
GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/yloove7/wuwa-calculator-Backup-/releases/latest"
)


def _run_git(
    *arguments: str,
    check: bool = False,
    capture_output: bool = False,
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        text=True,
        check=check,
        capture_output=capture_output,
        stdout=stdout,
        stderr=stderr,
    )


def _normalize_version(value: str) -> tuple[int, ...]:
    cleaned = re.sub(r"^[vV]", "", (value or "").strip())
    matches = re.findall(r"\d+", cleaned)
    if not matches:
        return (0,)
    return tuple(int(part) for part in matches)


def _select_release_asset(release_data: dict[str, object]) -> dict[str, object] | None:
    assets = release_data.get("assets")
    if not isinstance(assets, list):
        return None

    preferred_names = (
        "tethys",
        "wuwa-calculator",
        "wuwa_calculator",
        "tethys-windows",
        "tethys_windows",
        "windows",
    )

    candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", "")).lower()
        url = asset.get("browser_download_url")
        if not isinstance(url, str) or not url:
            continue
        if name.endswith(".exe") or name.endswith(".zip"):
            candidates.append(asset)

    if not candidates:
        return None

    for asset in candidates:
        name = str(asset.get("name", "")).lower()
        if any(token in name for token in preferred_names):
            return asset
    for asset in candidates:
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe"):
            return asset
    return candidates[0]


def _fetch_latest_release() -> dict[str, object] | None:
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Tethys-Updater",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"[UPDATER] Não foi possível consultar o GitHub Releases: {error}")
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        print("[UPDATER] GitHub Releases respondeu com JSON inválido.")
        return None

    if not isinstance(data, dict):
        return None
    return data


def _download_release_asset(asset: dict[str, object], target_name: str) -> Path | None:
    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not url:
        return None

    destination = REPOSITORY_ROOT / target_name
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "Tethys-Updater",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as file_handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                file_handle.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"[UPDATER] Falha ao baixar o asset do release: {error}")
        if destination.exists():
            destination.unlink()
        return None

    return destination


def _apply_pending_release_if_any() -> bool:
    """Apply a staged release asset to the current executable path when the next restart is ready."""
    staged_path = os.environ.get(PENDING_RELEASE_PATH_ENV)
    if not staged_path:
        return False

    staged = Path(staged_path).resolve()
    if not staged.exists():
        os.environ.pop(PENDING_RELEASE_PATH_ENV, None)
        return False

    target_exe = Path(sys.executable).resolve()
    try:
        backup_path = target_exe.with_name(f"{target_exe.name}.bak")
        if backup_path.exists():
            backup_path.unlink()
        if target_exe.exists():
            os.replace(target_exe, backup_path)
        os.replace(staged, target_exe)
        print(f"[UPDATER] Release aplicado em {target_exe} a partir de {staged}.")
        os.environ.pop(PENDING_RELEASE_PATH_ENV, None)
        os.environ.pop(PENDING_RELEASE_VERSION_ENV, None)
        return True
    except OSError as error:
        print(f"[UPDATER] Não foi possível substituir o executável em uso: {error}")
        return False


def is_git_checkout() -> bool:
    """Return True when the project is running from a real Git checkout."""
    result = _run_git(
        "rev-parse",
        "--is-inside-work-tree",
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def detect_update_mode() -> str:
    """Choose the active update path: Git checkout or packaged release."""
    if is_git_checkout():
        return "development"
    return "release"


def current_app_version() -> str:
    """Return the single source of truth for the current Tethys version."""
    return APP_VERSION


def _consume_update_applied_signal() -> bool:
    """Return True only for the restart cycle immediately after a successful pull or staged release update."""
    if os.environ.get(AUTO_UPDATE_APPLIED_ENV) == "1":
        os.environ.pop(AUTO_UPDATE_APPLIED_ENV, None)
        _apply_pending_release_if_any()
        print("[UPDATER] Reinício após atualização detectado; ignorando nova verificação no processo atual.")
        return True
    return False


def _worktree_is_clean() -> bool:
    """Return True only when the Git working tree is clear of local edits or untracked files."""
    resultado = _run_git(
        "status",
        "--porcelain",
        "--untracked-files=normal",
        capture_output=True,
        check=False,
    )
    return resultado.returncode == 0 and not resultado.stdout.strip()


def obter_info_commits_pendentes() -> tuple[int, str]:
    """Return the number of pending commits and their update messages."""
    try:
        _run_git(
            "fetch",
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        resultado = _run_git(
            "rev-list",
            "--count",
            "HEAD..@{u}",
            capture_output=True,
            check=True,
        )
        qtd_commits = int(resultado.stdout.strip())

        if qtd_commits > 0:
            log_resultado = _run_git(
                "log",
                "HEAD..@{u}",
                "--pretty=format:• %s (%h)",
                capture_output=True,
                check=True,
            )
            return qtd_commits, log_resultado.stdout.strip()

        return 0, ""
    except Exception as error:
        print(f"[UPDATER] Erro ao verificar Git: {error}")
        return 0, ""


_UPDATER_STYLE = """
    QDialog { background: #101318; color: #F3F4F6; }
    QLabel#updaterEyebrow { color: #D4A359; font-size: 10px; font-weight: 800; }
    QLabel#updaterTitle { color: #F3F4F6; font-size: 20px; font-weight: 800; }
    QLabel#updaterMessage { color: #B7BDC5; font-size: 12px; }
    QLabel#updaterCommitCount { color: #A0A7B0; font-size: 10px; font-weight: 700; }
    QFrame#updaterVersionCard { background: #1A1F25; border: 1px solid #343B43; border-radius: 10px; }
    QLabel#updaterVersionLabel { color: #A0A7B0; font-size: 10px; font-weight: 700; }
    QLabel#updaterVersionValue { color: #F3F4F6; font-size: 14px; font-weight: 800; }
    QTextEdit#updaterChanges { background: #15191E; color: #D7DBE0; border: 1px solid #343B43; border-radius: 8px; padding: 8px; font-family: Consolas, monospace; }
    QPushButton#updaterRepository { color: #D4A359; background: transparent; border: 0; padding: 4px 0; font-weight: 700; text-align: left; }
    QPushButton#updaterRepository:hover { color: #E2B76E; }
    QProgressBar#updaterProgress { background: #262B31; border: 0; border-radius: 4px; min-height: 8px; max-height: 8px; }
    QProgressBar#updaterProgress::chunk { background: #D4A359; border-radius: 4px; }
    QPushButton#updaterSecondary { color: #E5E7EB; background: #252A30; border: 1px solid #454C55; border-radius: 8px; padding: 9px 16px; font-weight: 700; }
    QPushButton#updaterSecondary:hover { background: #30363D; }
    QPushButton#updaterPrimary { color: #15110A; background: #D4A359; border: 1px solid #E2B76E; border-radius: 8px; padding: 9px 16px; font-weight: 800; }
    QPushButton#updaterPrimary:hover { background: #E2B76E; }
"""


class DialogoEstadoAtualizacao(QDialog):
    def __init__(
        self,
        title: str,
        message: str,
        *,
        technical_details: str | None = None,
        busy: bool = False,
        button_text: str = "Continuar",
    ) -> None:
        super().__init__()
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(_UPDATER_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(13)

        eyebrow = QLabel("TETHYS  /  ATUALIZAÇÃO")
        eyebrow.setObjectName("updaterEyebrow")
        heading = QLabel(title)
        heading.setObjectName("updaterTitle")
        heading.setWordWrap(True)
        body = QLabel(message)
        body.setObjectName("updaterMessage")
        body.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(body)

        if busy:
            progress = QProgressBar()
            progress.setObjectName("updaterProgress")
            progress.setRange(0, 0)
            progress.setTextVisible(False)
            layout.addWidget(progress)

        if technical_details:
            details = QTextEdit()
            details.setObjectName("updaterChanges")
            details.setReadOnly(True)
            details.setPlainText(technical_details)
            details.setMinimumHeight(90)
            layout.addWidget(details)

        if button_text:
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            button = QPushButton(button_text)
            button.setObjectName("updaterPrimary")
            button.clicked.connect(self.accept)
            buttons.addWidget(button)
            layout.addLayout(buttons)


class DialogoVerificandoAtualizacao(DialogoEstadoAtualizacao):
    def __init__(self) -> None:
        super().__init__(
            "Atualização do Tethys",
            "Verificando se há uma nova versão…",
            busy=True,
            button_text="",
        )
        self.setFixedSize(460, 190)


class DialogoAtualizacao(QDialog):
    def __init__(
        self,
        qtd_commits: int,
        historico_changes: str,
        *,
        current_version: str | None = None,
        new_version: str | None = None,
        simulated: bool = False,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Nova versão disponível")
        self.setFixedSize(560, 520)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(_UPDATER_STYLE)
        self.deve_atualizar = False
        self.simulated = simulated

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(13)
        eyebrow = QLabel("TETHYS  /  ATUALIZAÇÃO")
        eyebrow.setObjectName("updaterEyebrow")
        title = QLabel("Nova versão disponível")
        title.setObjectName("updaterTitle")
        title.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)

        versions = QHBoxLayout()
        versions.setSpacing(10)
        current_card = QFrame()
        current_card.setObjectName("updaterVersionCard")
        current_layout = QVBoxLayout(current_card)
        current_layout.setContentsMargins(13, 10, 13, 10)
        current_label = QLabel("VERSÃO ATUAL")
        current_label.setObjectName("updaterVersionLabel")
        actual_current_version = current_version or f"v{current_app_version()}"
        current_value = QLabel(actual_current_version)
        current_value.setObjectName("updaterVersionValue")
        current_layout.addWidget(current_label)
        current_layout.addWidget(current_value)
        update_card = QFrame()
        update_card.setObjectName("updaterVersionCard")
        update_layout = QVBoxLayout(update_card)
        update_layout.setContentsMargins(13, 10, 13, 10)
        update_label = QLabel("NOVA VERSÃO" if new_version else "ATUALIZAÇÃO DISPONÍVEL")
        update_label.setObjectName("updaterVersionLabel")
        update_value = QLabel(new_version or f"{qtd_commits} commits pendentes")
        update_value.setObjectName("updaterVersionValue")
        update_layout.addWidget(update_label)
        update_layout.addWidget(update_value)
        versions.addWidget(current_card, 1)
        versions.addWidget(update_card, 1)
        layout.addLayout(versions)

        if new_version:
            commits = QLabel(f"{qtd_commits} commits pendentes")
            commits.setObjectName("updaterVersionLabel")
            layout.addWidget(commits)

        message = QLabel("Uma nova versão do Tethys está pronta para ser instalada.")
        message.setObjectName("updaterMessage")
        message.setWordWrap(True)
        layout.addWidget(message)
        changes_label = QLabel("O que mudou")
        changes_label.setObjectName("updaterVersionLabel")
        layout.addWidget(changes_label)
        self.txt_changes = QTextEdit()
        self.txt_changes.setObjectName("updaterChanges")
        self.txt_changes.setReadOnly(True)
        self.txt_changes.setPlainText(historico_changes)
        self.txt_changes.setMinimumHeight(76)
        self.txt_changes.setMaximumHeight(124)
        layout.addWidget(self.txt_changes)

        changes_footer = QHBoxLayout()
        remaining_changes = max(0, qtd_commits - 5)
        commit_summary = QLabel(
            f"{qtd_commits} commits dispon\u00edveis"
            + (f" \u00b7 +{remaining_changes} outras altera\u00e7\u00f5es" if remaining_changes else "")
        )
        commit_summary.setObjectName("updaterCommitCount")
        changes_footer.addWidget(commit_summary)
        changes_footer.addStretch(1)
        repository_button = QPushButton("\U0001f310 Ver reposit\u00f3rio")
        repository_button.setObjectName("updaterRepository")
        repository_button.clicked.connect(self._open_repository)
        changes_footer.addWidget(repository_button)
        layout.addLayout(changes_footer)
        question = QLabel("Deseja instalar a atualização agora?")
        question.setObjectName("updaterMessage")
        layout.addWidget(question)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        later = QPushButton("Mais tarde")
        later.setObjectName("updaterSecondary")
        later.clicked.connect(self.recusar)
        update_now = QPushButton("Atualizar agora")
        update_now.setObjectName("updaterPrimary")
        update_now.clicked.connect(
            self._notify_simulated_update if simulated else self.aceitar
        )
        buttons.addWidget(later)
        buttons.addWidget(update_now)
        layout.addLayout(buttons)

    def _open_repository(self) -> None:
        webbrowser.open(GITHUB_RELEASES_URL)

    def aceitar(self) -> None:
        self.deve_atualizar = True
        self.accept()

    def recusar(self) -> None:
        self.deve_atualizar = False
        self.reject()

    def _notify_simulated_update(self) -> None:
        QMessageBox.information(
            self,
            "Simulação do Auto Update",
            "Simulação: a atualização seria iniciada aqui.",
        )


def _check_release_update() -> tuple[bool, str, dict[str, object] | None]:
    """Return whether the remote release is newer than the local version and its metadata."""
    latest = _fetch_latest_release()
    if not isinstance(latest, dict):
        return False, "", None

    remote_tag = str(latest.get("tag_name", "")).strip()
    if not remote_tag:
        return False, "", None

    local_version = _normalize_version(current_app_version())
    remote_version = _normalize_version(remote_tag)
    if remote_version <= local_version:
        return False, remote_tag, latest

    return True, remote_tag, latest


def _show_simulated_update() -> bool:
    sys.argv[:] = [argument for argument in sys.argv if argument != SIMULATE_UPDATE_FLAG]
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    dialog = DialogoAtualizacao(
        7,
        _SIMULATED_UPDATE_NOTES,
        current_version="v1.4.2",
        new_version="v1.5.0",
        simulated=True,
    )
    dialog.exec()
    return False


def executar_verificacao_e_update() -> bool:
    """Prompt for pending updates and restart after a successful pull or release staging."""
    global _AUTO_UPDATE_CHECK_RAN
    if SIMULATE_UPDATE_FLAG in sys.argv:
        return _show_simulated_update()

    if _AUTO_UPDATE_CHECK_RAN:
        print("[UPDATER] Verificação de atualização já executada nesta inicialização; ignorando nova checagem.")
        return False

    if _consume_update_applied_signal():
        _AUTO_UPDATE_CHECK_RAN = True
        return False

    _AUTO_UPDATE_CHECK_RAN = True
    mode = detect_update_mode()
    if mode == "release":
        print(f"[UPDATER] Modo executável detectado. Verificando GitHub Releases em {GITHUB_RELEASES_URL}.")
        print(f"[UPDATER] Versão local atual: {current_app_version()}")

        update_available, remote_tag, latest = _check_release_update()
        if not update_available:
            print(f"[UPDATER] Nenhuma atualização de release pendente a partir de {remote_tag or 'remote release'}.")
            return False

        asset = _select_release_asset(latest or {})
        if asset is None:
            print("[UPDATER] Nenhum asset compatível foi encontrado no release mais recente.")
            return False

        asset_name = str(asset.get("name", "release.bin"))
        staged_path = _download_release_asset(asset, f"{Path(asset_name).stem or 'tethys'}_{remote_tag}.download")
        if staged_path is None:
            return False

        os.environ[PENDING_RELEASE_PATH_ENV] = str(staged_path)
        os.environ[PENDING_RELEASE_VERSION_ENV] = remote_tag
        print(f"[UPDATER] Atualização de release preparada em {staged_path}. Reiniciando para aplicar o executável novo.")
        print(f"[UPDATER] Nova versão remota: {remote_tag}")
        os.environ[AUTO_UPDATE_APPLIED_ENV] = "1"
        os.execv(sys.executable, [sys.executable, *sys.argv])
        return True

    app_temp = QApplication.instance()
    if app_temp is None:
        app_temp = QApplication(sys.argv)

    dialogo_verificacao = DialogoVerificandoAtualizacao()
    dialogo_verificacao.show()
    app_temp.processEvents()

    qtd, historico = obter_info_commits_pendentes()
    dialogo_verificacao.close()
    dialogo_verificacao.deleteLater()

    if qtd == 0:
        print("[UPDATER] Tethys já está na versão mais recente.")
        return False

    if not _worktree_is_clean():
        status = _run_git(
            "status",
            "--porcelain",
            "--untracked-files=normal",
            capture_output=True,
            check=False,
        )
        print("[UPDATER] Não foi possível aplicar a atualização automática: há alterações locais no repositório.")
        print("[UPDATER] O Git working tree não está limpo. Nenhum arquivo foi alterado ou sobrescrito.")
        if status.stdout.strip():
            print(status.stdout.strip())
        return False

    dialogo = DialogoAtualizacao(qtd, historico)
    dialogo.exec()

    if not dialogo.deve_atualizar:
        print("[UPDATER] Usuário optou por iniciar sem atualizar.")
        return False

    print("[UPDATER] Aplicando git pull...")
    instalando = DialogoEstadoAtualizacao(
        "Instalando atualiza\u00e7\u00e3o\u2026",
        "N\u00e3o feche o Tethys enquanto a atualiza\u00e7\u00e3o est\u00e1 sendo instalada.",
        busy=True,
        button_text="",
    )
    instalando.show()
    app_temp.processEvents()
    try:
        _run_git("pull", check=True)
        instalando.close()
        print("[UPDATER] Atualização concluída! Reiniciando...")
        os.environ[AUTO_UPDATE_APPLIED_ENV] = "1"
        os.execv(sys.executable, [sys.executable, *sys.argv])
        return True
    except Exception as error:
        instalando.close()
        print(f"[UPDATER] Erro ao aplicar pull: {error}")
        DialogoEstadoAtualizacao(
            "N\u00e3o foi poss\u00edvel concluir a atualiza\u00e7\u00e3o.",
            "O Tethys n\u00e3o conseguiu instalar a atualiza\u00e7\u00e3o. Voc\u00ea pode continuar usando a vers\u00e3o atual.",
            technical_details=str(error),
        ).exec()
        return False
