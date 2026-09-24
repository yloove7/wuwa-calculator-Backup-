"""Standalone OCR process used to keep PaddleOCR out of the Qt process."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

from src.wuwa_calculator.utils.ocr import extract_image_data


def _status(message: str) -> None:
    output = sys.__stdout__
    if output is not None:
        output.write(f"STATUS\t{message}\n")
        output.flush()


def main() -> int:
    if len(sys.argv) != 2:
        print("ERROR\tArgumento de imagem ausente", flush=True)
        return 2
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            stats, detected_id, echoes = extract_image_data(
                Path(sys.argv[1]),
                status_callback=_status,
            )
        print(
            "RESULT\t" + json.dumps(
                {"stats": stats, "character_id": detected_id, "echoes": echoes},
                ensure_ascii=True,
            ),
            flush=True,
        )
        return 0
    except Exception as error:  # pylint: disable=broad-except
        print(f"ERROR\t{type(error).__name__}: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
