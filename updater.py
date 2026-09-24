"""Check for and apply updates from the repository's configured remote."""

import os
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent
_AUTO_UPDATE_CHECK_RAN = False


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


def verificar_e_atualizar() -> bool:
    """Update the checkout and restart the application when a commit is newer."""
    global _AUTO_UPDATE_CHECK_RAN
    if _AUTO_UPDATE_CHECK_RAN:
        print("[AUTO-UPDATER] Verificação de atualização já executada nesta inicialização; ignorando nova checagem.")
        return False
    _AUTO_UPDATE_CHECK_RAN = True

    print("[AUTO-UPDATER] Verificando atualizações no repositório...")

    try:
        _run_git(
            "fetch",
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        commit_local = _run_git(
            "rev-parse",
            "HEAD",
            capture_output=True,
            check=True,
        ).stdout.strip()
        commit_remoto = _run_git(
            "rev-parse",
            "@{u}",
            capture_output=True,
            check=True,
        ).stdout.strip()

        if commit_local == commit_remoto:
            print("[AUTO-UPDATER] O Tethys já está na versão mais recente.")
            return False

        print("[AUTO-UPDATER] Novo commit detectado! Atualizando o Tethys...")
        _run_git("pull", check=True)
        print("[AUTO-UPDATER] Atualização concluída com sucesso!")
        reiniciar_aplicacao()
        return True
    except subprocess.CalledProcessError:
        print(
            "[AUTO-UPDATER] Erro ao comunicar com o Git remoto "
            "(verifique a conexão ou se o repositório está configurado)."
        )
        return False
    except OSError as error:
        print(f"[AUTO-UPDATER] Falha ao executar o Git: {error}")
        return False
    except Exception as error:
        print(f"[AUTO-UPDATER] Falha inesperada no auto-update: {error}")
        return False


def reiniciar_aplicacao() -> None:
    """Replace the current Python process with the updated application."""
    print("[AUTO-UPDATER] Reiniciando a aplicação...")
    os.execv(sys.executable, [sys.executable, *sys.argv])
