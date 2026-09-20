"""Graphical updater prompt for the Tethys launcher."""

import os
from pathlib import Path
import subprocess
import sys

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


REPOSITORY_ROOT = Path(__file__).resolve().parent


def _run_git(*arguments: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        text=True,
        **kwargs,
    )


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


def executar_verificacao_e_update() -> bool:
    """Prompt for pending updates and restart after a successful pull."""
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

    dialogo = DialogoAtualizacao(qtd, historico)
    dialogo.exec()

    if not dialogo.deve_atualizar:
        print("[UPDATER] Usuário optou por iniciar sem atualizar.")
        return False

    print("[UPDATER] Aplicando git pull...")
    try:
        _run_git("pull", check=True)
        print("[UPDATER] Atualização concluída! Reiniciando...")
        os.execv(sys.executable, [sys.executable, *sys.argv])
        return True
    except Exception as error:
        print(f"[UPDATER] Erro ao aplicar pull: {error}")
        return False