"""Initial screen rules known before any learning has happened."""

from __future__ import annotations

import re
import unicodedata

BLOCKED_CAPTURE_STATES = frozenset({
    "LOGIN",
    "CARREGANDO",
    "EM_MENU",
    "MAPA_ABERTO",
    "INTERFACE_OU_MENU",
    "PRE_COMBATE",
    "FIM_DE_COMBATE",
    "TELA_DE_RECOMPENSA",
    "FORA_DO_JOGO",
})


def normalize_screen_text(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text).casefold()
        if not unicodedata.combining(character)
    )


def classify_screen_text(text: str) -> dict[str, bool]:
    """Classify known loading, result, reward, and login anchors."""
    normalized = normalize_screen_text(text)
    return {
        "completion": "desafio concluido" in normalized or "confirmar pontuacao" in normalized,
        "pre_combat": "relatorio ambiental" in normalized or "efeito de area" in normalized,
        "reward_screen": any(
            phrase in normalized
            for phrase in (
                "resgatar",
                "recompensas obtidas",
                "waveplates",
                "placa de ondulacao",
                "drops de ecos",
            )
        ),
        "login": any(
            phrase in normalized
            for phrase in ("iniciar jogo", "servidor", "america", "europa", "asia")
        ),
        "loading": bool(
            re.search(r"\b\d{1,3}\s*%", normalized)
            or re.search(r"\b\d+(?:\.\d+)?\s*(?:mb|kb)\s*/\s*s\b", normalized)
            or any(
                phrase in normalized
                for phrase in (
                    "carregando",
                    "loading",
                    "dica de tela",
                    "compiling shaders",
                    "compilando shaders",
                    "checking updates",
                    "verificando atualizacoes",
                    "atualizando",
                    "verificando arquivos",
                )
            )
        ),
    }
