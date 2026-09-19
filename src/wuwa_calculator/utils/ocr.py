# captura os stats de uma imagem usando OCR + regex
# para capturar os stats, a imagem precisa estar
# em escala de cinza e com contraste/nitidez aumentados
from __future__ import annotations

import os
import re
import sys
import json
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher

from pathlib import Path

# Desativa o MKL-DNN por compatibilidade entre builds do PaddlePaddle.
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
# PaddleOCR ainda inclui protos antigos incompatíveis com protobuf 4+.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.wuwa_calculator.utils.image_processing import prepare_for_ocr  # pylint: disable=wrong-import-position
from src.wuwa_calculator.data.characters_ids import KNOWN_CHARACTER_IDS
from src.wuwa_calculator.data.echoes import ECHOES_DB

SEP = r"\s*[:=]?\s*"
NUMBER = r"(?:[Xx×*]?\s*)?([-+]?\d[\d.,]*)"
PERCENT = r"\s*%?"

ELEMENTS = (
    "Electro", "Spectro",
    "Havoc", "Fusion",
    "Glacio", "Aero",)

ELEMENT_PATTERN = "|".join(ELEMENTS)

_ocr_engine = None


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from paddleocr import PaddleOCR

        _ocr_engine = PaddleOCR(lang="en")
    return _ocr_engine

STAT_PATTERNS: dict[str, re.Pattern[str]] = {
    "atk": re.compile(
        rf"\bATK\b{SEP}{NUMBER}",
        re.IGNORECASE
        ),
    "hp": re.compile(
        rf"\bHP\b{SEP}{NUMBER}", re.IGNORECASE
        ),
    "def": re.compile(
        rf"\bDEF\b{SEP}{NUMBER}", re.IGNORECASE
        ),
    "crit_rate": re.compile(
        rf"\bCrit(?:ical)?\.?\s*(?:R(?:ate|ote)|Taxa)\b"
        rf"{SEP}{NUMBER}\s*{PERCENT}", re.IGNORECASE
    ),
    "crit_dmg": re.compile(
        rf"\bCrit(?:ical)?\.?\s*(?:DMG|Damage|Dano)\b"
        rf"{SEP}{NUMBER}\s*{PERCENT}", re.IGNORECASE
    ),
}


def extract_text_from_paddle_result(result) -> str:
    """Normaliza a saída do PaddleOCR 3.x para um texto único."""
    lines: list[str] = []

    pages = result if isinstance(result, (list, tuple)) else [result]
    for page in pages:
        try:
            data = getattr(page, "json", page)
        except (AttributeError, IndexError, TypeError):
            continue
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        if isinstance(data, (list, tuple)):
            lines.extend(extract_text_from_paddle_result(data).splitlines())
            continue
        if not isinstance(data, dict):
            continue
        # algumas versões colocam tudo em "res"
        data = data.get("res", data)
        if not isinstance(data, dict):
            continue
        texts = data.get("rec_texts") or data.get("rec_text") or []
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, (list, tuple)):
            continue
        for text in texts:
            if text is not None:
                cleaned = str(text).strip()
                if cleaned:
                    lines.append(cleaned)
    return "\n".join(lines)


def _normalise_character(value: str) -> str:
    folded = "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "", folded)


def _normalise_ocr_noise(text: str) -> str:
    """Remove prefixos típicos de leitura OCR antes de números, como X18% ou *12%."""
    cleaned = str(text)
    cleaned = cleaned.replace("×", "x")
    cleaned = re.sub(r"(?i)\b(?:atk|hp|def|crit|energy|heavy|skill|liberation|elemental|damage|dmg)\s+[x*]\s*(?=\d)", lambda match: match.group(0).split("x")[0].split("*")[0] + " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:set|cost|main|sub)\s+[x*]\s*(?=\d)", lambda match: match.group(0).split("x")[0].split("*")[0] + " ", cleaned)
    cleaned = re.sub(r"(?i)\b[x*]\s*(?=\d{1,3}(?:[.,]\d+)?%?)", " ", cleaned)
    return cleaned


def identify_character(text: str) -> str | None:
    """Identifica o personagem pelo nome lido no topo da build card."""
    candidates = text.splitlines()[:8]
    normalised_ids = {
        _normalise_character(character_id): character_id
        for character_id in KNOWN_CHARACTER_IDS
    }
    for candidate in candidates:
        normalised = _normalise_character(candidate)
        if normalised in normalised_ids:
            return normalised_ids[normalised]
        for normalised_id, character_id in normalised_ids.items():
            if normalised_id and normalised_id in normalised:
                return character_id
    text_normalised = _normalise_character(text)
    for normalised_id, character_id in normalised_ids.items():
        if normalised_id and normalised_id in text_normalised:
            return character_id
    return None


def identify_echoes(text: str) -> list[str]:
    """Find known Echo names without assuming a provider-specific card layout."""
    normalized_text = _normalise_character(text)
    matches: list[str] = []
    for echo_id, data in ECHOES_DB.items():
        name = str(data.get("name", echo_id)) if isinstance(data, dict) else echo_id
        normalized_name = _normalise_character(name)
        if normalized_name and normalized_name in normalized_text:
            matches.append(name)
    return matches[:5]


def _echo_attribute_lines(lines: list[str]) -> list[str]:
    attributes: list[str] = []
    label_patterns = (
        (r"crit(?:ical)?\s*(?:rate|rote)", "Crit Rate"),
        (r"crit(?:ical)?\s*(?:dmg|damage|dano)", "Crit DMG"),
        (r"energy\s*(?:regen|recharge)", "Energy Regen"),
        (r"heavy\s*attack", "Heavy Attack"),
        (r"resonance\s*skill|skill\s*dmg", "Skill DMG"),
        (r"resonance\s*liberation|liberation\s*dmg", "Liberation DMG"),
        (r"elemental\s*dmg|electro\s*dmg|fusion\s*dmg|aero\s*dmg|glacio\s*dmg", "Elemental DMG"),
        (r"\batk\b|attack", "ATK"),
        (r"\bhp\b|health", "HP"),
        (r"\bdef\b|defense", "DEF"),
    )
    for line in lines:
        cleaned = re.sub(r"[x×]\s*(?=\d)", "", str(line), flags=re.IGNORECASE)
        cleaned = re.sub(r"[^\w%+.,: -]", " ", cleaned, flags=re.UNICODE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" :-")
        if not cleaned or not re.search(r"\d", cleaned):
            continue
        number_match = re.search(r"[-+]?\d+(?:[.,]\d+)?\s*%?", cleaned)
        if not number_match:
            continue
        label = None
        for pattern, normalized_label in label_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                label = normalized_label
                break
        if label is None:
            continue
        value = number_match.group(0).replace(" ", "")
        suffix = "%" if "%" in value or label in {
            "Crit Rate", "Crit DMG", "Energy Regen", "Heavy Attack",
            "Skill DMG", "Liberation DMG", "Elemental DMG",
        } else ""
        attributes.append(f"{label} +{value.rstrip('%')}" + suffix)
    return attributes[:8]


def _echo_catalog_data(name: str) -> dict[str, object]:
    normalized_name = _normalise_character(name)
    for echo_id, data in ECHOES_DB.items():
        if not isinstance(data, dict):
            continue
        candidate = _normalise_character(str(data.get("name", echo_id)))
        if candidate and (candidate in normalized_name or normalized_name in candidate):
            return data
    return {}


def _infer_dynamic_cost(main_stat: str) -> int:
    """Determina o custo de forma genérica a partir do valor do Main Stat lido."""
    text = (main_stat or "").casefold()
    if not text:
        return 0
    value_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%?", text)
    value = float(value_match.group(1).replace(",", ".")) if value_match else 0.0
    has_crit = "crit" in text
    has_healing = "healing" in text or "heal" in text
    has_elemental = any(token in text for token in ("elemental", "dmg", "damage", "attribute"))
    has_energy = "energy" in text or "regen" in text
    has_atk = "atk" in text
    has_flat_stat = any(token in text for token in ("hp", "def", "flat"))

    if value >= 44 or (value >= 30 and (has_crit or has_healing or has_atk)):
        return 4
    if (value >= 30 and has_elemental) or (value >= 18 and (has_energy or has_atk)):
        return 3
    if value in (10, 12) or has_flat_stat:
        return 1
    return 0


def _infer_echo_cost(main_stat: str) -> int:
    return _infer_dynamic_cost(main_stat)


def _parse_dynamic_echo_block(lines: list[str]) -> dict[str, object]:
    """Parseia um bloco de Echo sem depender de nomes fixos ou de layout específico."""
    sanitized = [_normalise_ocr_noise(line).strip() for line in lines if line and line.strip()]
    if not sanitized:
        return {
            "slot": 0,
            "name": "Echo",
            "main_stat": "--",
            "sub_stats": [],
            "cost": 0,
            "set_bonus": "--",
            "attributes": [],
        }

    def _first_non_label_line() -> str:
        for candidate in sanitized:
            lowered = candidate.casefold()
            if any(token in lowered for token in ("cost", "set", "sonata", "crit", "atk", "hp", "def")):
                continue
            if re.search(r"\d", candidate):
                continue
            return candidate
        return sanitized[0]

    name = _first_non_label_line()
    cost_match = next(
        (
            re.search(r"(?i)\bcost\b\s*[:=]?\s*([1-4])\b", line)
            for line in sanitized
            if re.search(r"(?i)\bcost\b", line)
        ),
        None,
    )
    set_match = next(
        (
            re.search(r"(?i)\b(?:set|sonata|conjunto)\b\s*[:=]?\s*([A-Za-z0-9'\- ][A-Za-z0-9'\- ]{2,40})", line)
            for line in sanitized
            if re.search(r"(?i)\b(?:set|sonata|conjunto)\b", line)
        ),
        None,
    )
    main_stat = "--"
    sub_stats: list[str] = []
    stat_candidates: list[tuple[float, str, str]] = []
    main_pattern = re.compile(
        r"(?i)(ATK|HP|DEF|Crit(?:ical)?\s*(?:Rate|DMG)|Energy\s*(?:Regen|Recharge)|Heavy\s*Attack|Skill\s*DMG|Liberation\s*DMG|Elemental\s*DMG|(?:Electro|Spectro|Havoc|Fusion|Glacio|Aero)\s*(?:DMG|Damage|Bonus)|Healing\s*Bonus|HP\s*Regen)\s*[:=]?\s*([Xx*]?\s*[-+]?\d[\d.,]*%?)"
    )
    for line in sanitized:
        if re.search(r"(?i)\b(?:cost|set|sonata|conjunto)\b", line):
            continue
        match = main_pattern.search(line)
        if match:
            label, raw_value = match.groups()
            parsed_value = clean_number(raw_value)
            if parsed_value is not None:
                stat_candidates.append((float(parsed_value), label.strip(), line.strip()))
                continue
        if re.search(r"(?i)(ATK|HP|DEF|Crit|Energy|Heavy|Skill|Liberation|Elemental|Damage|DMG|Regen)", line):
            value_match = re.search(r"[-+]?\d[\d.,]*%?", line)
            if value_match:
                parsed_value = clean_number(value_match.group(0))
                if parsed_value is not None:
                    stat_candidates.append((float(parsed_value), re.search(r"(?i)(ATK|HP|DEF|Crit|Energy|Heavy|Skill|Liberation|Elemental|Damage|DMG|Regen)", line).group(1).strip(), line.strip()))

    if stat_candidates:
        best_value, best_label, best_line = max(stat_candidates, key=lambda item: (abs(item[0]), item[1].lower() != "atk"))
        main_stat = f"{best_label}: +{best_value:g}%" if "%" in str(best_line) or "crit" in best_label.casefold() or "energy" in best_label.casefold() else f"{best_label}: +{best_value:g}"

    for line in sanitized:
        if re.search(r"(?i)\b(?:cost|set|sonata|conjunto)\b", line):
            continue
        if main_stat != "--" and line.strip() == best_line if 'best_line' in locals() else False:
            continue
        if re.search(r"(?i)(ATK|HP|DEF|Crit|Energy|Heavy|Skill|Liberation|Elemental|Damage|DMG|Regen)", line):
            cleaned_line = _normalise_ocr_noise(line)
            if cleaned_line and cleaned_line not in {main_stat, "--"}:
                sub_stats.append(cleaned_line)

    if main_stat == "--":
        for line in sanitized:
            value_match = re.search(r"[-+]?\d[\d.,]*%?", line)
            label_match = re.search(r"(?i)(ATK|HP|DEF|Crit|Energy|Heavy|Skill|Liberation|Elemental|Damage|DMG|Regen)", line)
            if value_match and label_match:
                label = label_match.group(1).strip()
                value = clean_number(value_match.group(0))
                if value is not None:
                    main_stat = f"{label}: +{value:g}%" if "%" in value_match.group(0) else f"{label}: +{value:g}"
                    break

    cost_value = 0
    if cost_match:
        cost_value = int(cost_match.group(1))
    else:
        cost_value = _infer_dynamic_cost(main_stat)

    set_bonus = "--"
    if set_match:
        set_bonus = set_match.group(1).strip()
    elif any(re.search(r"(?i)\b(?:set|sonata|conjunto)\b", line) for line in sanitized):
        for line in sanitized:
            if re.search(r"(?i)\b(?:set|sonata|conjunto)\b", line):
                set_bonus = line.split(":", 1)[-1].strip() if ":" in line else line
                break

    if not sub_stats and main_stat != "--":
        for line in sanitized:
            if any(token in line.casefold() for token in ("crit", "atk", "hp", "def", "energy", "heavy", "skill", "liberation", "elemental", "damage", "dmg")):
                candidate = _normalise_ocr_noise(line)
                if candidate and candidate != main_stat:
                    sub_stats.append(candidate)

    if not main_stat or main_stat == "--":
        main_stat = "--"

    return {
        "slot": 0,
        "name": name,
        "main_stat": main_stat,
        "sub_stats": sub_stats[:5],
        "cost": cost_value,
        "set_bonus": set_bonus,
        "attributes": [main_stat, *sub_stats[:5]] if main_stat != "--" else sub_stats[:5],
    }


def identify_echo_cards(text: str) -> list[dict[str, object]]:
    """Recupera Echo cards genéricas a partir de qualquer build card, sem nomes fixos."""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return []

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in raw_lines:
        is_cost_line = re.search(r"(?i)\b(?:cost|custo)\b", line)
        has_echo_content = bool(current) and any(
            re.search(r"(?i)\b(?:set|sonata|conjunto|crit|atk|hp|def|energy|heavy|skill|liberation|elemental|dmg|damage)\b", segment)
            for segment in current
        )
        if is_cost_line and current and has_echo_content:
            blocks.append(current)
            current = [line]
            continue
        if is_cost_line and not current:
            current = [line]
            continue
        if current and is_cost_line and not has_echo_content:
            current.append(line)
            continue
        if current and re.search(r"(?i)\b(?:set|sonata|conjunto|crit|atk|hp|def|energy|heavy|skill|liberation|elemental|dmg|damage)\b", line):
            current.append(line)
            continue
        if current:
            current.append(line)
        else:
            current = [line]
    if current:
        blocks.append(current)

    echos_list: list[dict[str, object] | None] = [None] * 5
    for index, block in enumerate(blocks[:5]):
        card = _parse_dynamic_echo_block(block)
        card["slot"] = index
        card["name"] = str(card.get("name", f"Echo {index + 1}"))
        echos_list[index] = card

    filled = [card for card in echos_list if card is not None]
    if not filled:
        fallback = _parse_dynamic_echo_block(raw_lines)
        fallback["slot"] = 0
        fallback["name"] = str(fallback.get("name", "Echo 1"))
        filled.append(fallback)

    ordered = []
    for card in filled[:5]:
        card["slot"] = len(ordered)
        ordered.append(card)
    return ordered


def _same_echo_name(first: object, second: object) -> bool:
    first_normalized = _normalise_character(str(first))
    second_normalized = _normalise_character(str(second))
    return bool(
        first_normalized
        and second_normalized
        and (
            first_normalized == second_normalized
            or first_normalized in second_normalized
            or second_normalized in first_normalized
        )
    )


def _merge_echo_card_data(
    primary: list[dict[str, object]],
    supplemental: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Merge full-image and per-card OCR without losing attributes."""
    merged = [dict(card) for card in primary]
    for extra in supplemental:
        target = next(
            (card for card in merged if _same_echo_name(card.get("name"), extra.get("name"))),
            None,
        )
        if target is None:
            merged.append(dict(extra))
            continue
        for key in ("main_stat", "cost", "set_bonus"):
            current = target.get(key)
            incoming = extra.get(key)
            if current in (None, "", "--", 0) and incoming not in (None, "", "--", 0):
                target[key] = incoming
        if target.get("cost") in (None, "", "--", 0):
            target["cost"] = _infer_echo_cost(str(target.get("main_stat", "--")))
        for key in ("attributes", "sub_stats"):
            current_values = target.get(key, [])
            incoming_values = extra.get(key, [])
            combined: list[str] = []
            for value in (
                current_values if isinstance(current_values, list) else [],
                incoming_values if isinstance(incoming_values, list) else [],
            ):
                for item in value:
                    if str(item) not in combined:
                        combined.append(str(item))
            target[key] = combined
        target["main_stat"] = target.get("main_stat") or extra.get("main_stat", "--")
    for index, card in enumerate(merged[:5], 1):
        card["slot"] = index
    return merged[:5]


def clean_number(raw: str | None) -> float | None:
    """Converte o número reconhecido pelo OCR para float."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = _normalise_ocr_noise(text)
    text = text.replace("%", "").replace(" ", "")
    text = re.sub(r"[A-Za-z]", "", text)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        integer, fraction = text.rsplit(",", 1)
        text = text.replace(",", "") if len(fraction) == 3 else f"{integer}.{fraction}"
    else:
        text = text.replace(",", "")
    if text in {"", "+", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def extract_stats_from_text(text: str) -> dict[str, float]:
    """Texto bruto do OCR → dicionário de atributos."""
    clean_text = _normalise_ocr_noise(text)
    clean_text = re.sub(r"(?i)crit\s*[.:,;]?\s*(dmg|damage|dano)", r"Crit DMG", clean_text)
    clean_text = re.sub(r"(?i)crit\s*[.:,;]?\s*(rate|rote|taxa)", r"Crit Rate", clean_text)
    stats: dict[str, float] = {}
    for key, pattern in STAT_PATTERNS.items():
        match = pattern.search(clean_text)
        if not match:
            continue
        value = clean_number(match.group(1))
        if value is not None:
            stats[key] = value
    return stats


def extract_stats_from_image(path: str | Path) -> dict[str, float]:
    """Imagem → PaddleOCR → texto → dicionário de stats."""
    stats, _, _ = extract_image_data(path)
    return stats


def extract_image_data(
    path: str | Path,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[dict[str, float], str | None, list[dict[str, object]]]:
    """Imagem → texto, atributos reconhecidos e personagem identificado."""
    path = Path(path)
    print("[Importação] Extraindo atributos base da imagem...")
    ocr_engine = _get_ocr_engine()
    import numpy as np

    def emit_status(message: str) -> None:
        if status_callback is not None:
            status_callback(message)

    emit_status("Lendo somente os atributos base...")
    text = ""
    try:
        prepared = prepare_for_ocr(path, width=1280).convert("RGB")
        result = ocr_engine.predict(np.asarray(prepared))
        text = extract_text_from_paddle_result(result)
    except (IndexError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        emit_status(f"Falha na leitura dos atributos ({type(error).__name__})...")

    stats = extract_stats_from_text(text)
    emit_status("Atributos base identificados.")
    print(f"[Importação] Texto encontrado: {text}")
    return stats, identify_character(text), []


if __name__ == "__main__":
    from src.wuwa_calculator.app.main import select_image  # pylint: disable=import-outside-toplevel,no-name-in-module
    img_prepared = prepare_for_ocr(select_image())
    img_prepared.save("utils/ocr_output.png")
    img_prepared.show()
