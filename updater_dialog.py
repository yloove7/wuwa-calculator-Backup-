"""Graphical updater prompt for the Tethys launcher."""

import json
import os
import re
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
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
GITHUB_RELEASES_URL = "https://github.com/yloove7/wuwa-calculator-Backup-/releases"
GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/yloove7/wuwa-calculator-Backup-/releases/latest"
)


def _run_git(*arguments: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        text=True,
        **kwargs,
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


class DialogoVerificandoAtualizacao(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TETHYS - Verificando atualizações")
        self.setFixedSize(320, 110)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint
        )

        layout = QVBoxLayout(self)
        mensagem = QLabel("Verificando atualizações...\nAguarde um momento.")
        mensagem.setAlignment(Qt.AlignCenter)
        layout.addWidget(mensagem)

        progresso = QProgressBar()
        progresso.setRange(0, 0)
        progresso.setTextVisible(False)
        progresso.setFixedHeight(18)
        progresso.setStyleSheet(
            """
            QProgressBar {
                background-color: #D6DFF7;
                border: 1px solid #7F9DB9;
                border-radius: 2px;
                padding: 2px;
            }
            QProgressBar::chunk {
                background-color: #39B54A;
                margin: 1px;
                width: 22px;
            }
            """
        )
        layout.addWidget(progresso)


class DialogoAtualizacao(QDialog):
    def __init__(self, qtd_commits: int, historico_changes: str) -> None:
        super().__init__()
        self.setWindowTitle("TETHYS - Atualização Disponível")
        self.setFixedSize(500, 380)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint
        )
        self.deve_atualizar = False

        layout = QVBoxLayout(self)

        lbl_titulo = QLabel("🚀 Nova Atualização Encontrada!")
        font_titulo = QFont()
        font_titulo.setPointSize(14)
        font_titulo.setBold(True)
        lbl_titulo.setFont(font_titulo)
        lbl_titulo.setStyleSheet("color: #00ADB5;")
        layout.addWidget(lbl_titulo)

        lbl_info = QLabel(
            f"O repositório possui <b>{qtd_commits} novo(s) commit(s)</b> pendente(s)."
        )
        layout.addWidget(lbl_info)

        layout.addWidget(QLabel("O que mudou nesta versão:"))

        self.txt_changes = QTextEdit()
        self.txt_changes.setReadOnly(True)
        self.txt_changes.setPlainText(historico_changes)
        self.txt_changes.setStyleSheet(
            """
            QTextEdit {
                background-color: #1E1E1E;
                color: #EEEEEE;
                border: 1px solid #393E46;
                border-radius: 5px;
                font-family: Consolas, monospace;
            }
            """
        )
        layout.addWidget(self.txt_changes)

        lbl_pergunta = QLabel("Deseja aplicar as atualizações agora?")
        font_pergunta = QFont()
        font_pergunta.setBold(True)
        lbl_pergunta.setFont(font_pergunta)
        layout.addWidget(lbl_pergunta)

        layout_botoes = QHBoxLayout()

        btn_nao = QPushButton("Agora Não (Iniciar Tethys)")
        btn_nao.setStyleSheet(
            "padding: 8px; background-color: #393E46; color: white; border-radius: 4px;"
        )
        btn_nao.clicked.connect(self.recusar)

        btn_sim = QPushButton("Atualizar e Reiniciar")
        btn_sim.setStyleSheet(
            "padding: 8px; background-color: #00ADB5; color: white; "
            "font-weight: bold; border-radius: 4px;"
        )
        btn_sim.clicked.connect(self.aceitar)

        layout_botoes.addWidget(btn_nao)
        layout_botoes.addWidget(btn_sim)
        layout.addLayout(layout_botoes)

    def aceitar(self) -> None:
        self.deve_atualizar = True
        self.accept()

    def recusar(self) -> None:
        self.deve_atualizar = False
        self.reject()


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


def executar_verificacao_e_update() -> bool:
    """Prompt for pending updates and restart after a successful pull or release staging."""
    global _AUTO_UPDATE_CHECK_RAN
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
    try:
        _run_git("pull", check=True)
        print("[UPDATER] Atualização concluída! Reiniciando...")
        os.environ[AUTO_UPDATE_APPLIED_ENV] = "1"
        os.execv(sys.executable, [sys.executable, *sys.argv])
        return True
    except Exception as error:
        print(f"[UPDATER] Erro ao aplicar pull: {error}")
        return False