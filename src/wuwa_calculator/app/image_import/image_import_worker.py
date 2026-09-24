"""Image import worker and its character mismatch error."""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TypedDict

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QImageReader


class ImageImportResult(TypedDict):
    stats: dict[str, float]
    character_id: str | None
    echoes: list[dict[str, object]]


class ImageCharacterMismatchError(ValueError):
    def __init__(self, detected_id: str, expected_id: str) -> None:
        super().__init__(
            f"A imagem foi identificada como '{detected_id}', "
            f"mas a aba aberta é '{expected_id}'."
        )
        self.detected_id = detected_id
        self.expected_id = expected_id


class ImageImportWorker(QObject):
    preview_ready = Signal(QImage)
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(dict)
    failed = Signal(object)

    PROCESS_TIMEOUT_SECONDS = 180.0
    PROCESS_TERMINATE_TIMEOUT_SECONDS = 2.0

    def __init__(self, path: str, target_id: str) -> None:
        super().__init__()
        self.path = path
        self.target_id = target_id
        self._cancel_requested = threading.Event()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _finish_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=self.PROCESS_TERMINATE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        with self._process_lock:
            if self._process is process:
                self._process = None

    def run(self) -> None:
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            preview = reader.read()
            if not preview.isNull():
                preview = preview.scaled(
                    1200,
                    900,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.preview_ready.emit(preview)
            self.status.emit("Iniciando leitor isolado da build card...")
            self.progress.emit(15)
            project_root = str(Path(__file__).resolve().parents[3])
            command = [
                sys.executable,
                "-m",
                "src.wuwa_calculator.utils.ocr_process",
                self.path,
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if self._cancel_requested.is_set():
                raise InterruptedError("Importação OCR cancelada.")
            process: subprocess.Popen[str] = subprocess.Popen(
                command,
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
            with self._process_lock:
                self._process = process
            deadline = time.monotonic() + self.PROCESS_TIMEOUT_SECONDS
            output = ""
            while True:
                if self._cancel_requested.is_set():
                    raise InterruptedError("Importação OCR cancelada.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, self.PROCESS_TIMEOUT_SECONDS)
                try:
                    output, _ = process.communicate(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            result: dict[str, object] | None = None
            for raw_line in output.splitlines():
                line = raw_line.rstrip()
                prefix, separator, payload = line.partition("\t")
                if not separator:
                    continue
                if prefix == "STATUS":
                    self.status.emit(payload)
                elif prefix == "RESULT":
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        result = parsed
            return_code = process.returncode
            if self._cancel_requested.is_set():
                raise InterruptedError("Importação OCR cancelada.")
            if return_code != 0 or result is None:
                error_text = "Leitor OCR encerrou sem resultado."
                raise RuntimeError(error_text)
            raw_stats = result.get("stats", {})
            if not isinstance(raw_stats, dict):
                raise RuntimeError(
                    "Leitor OCR retornou atributos em formato inválido."
                )
            stats: dict[str, float] = {}
            for key, value in raw_stats.items():
                if (
                    not isinstance(key, str)
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    raise RuntimeError(
                        "Leitor OCR retornou atributos em formato inválido."
                    )
                stats[key] = float(value)
            raw_detected_id = result.get("character_id")
            if raw_detected_id is not None and not isinstance(raw_detected_id, str):
                raise RuntimeError(
                    "Leitor OCR retornou um identificador de personagem inválido."
                )
            detected_id = raw_detected_id
            raw_echoes = result.get("echoes", [])
            if not isinstance(raw_echoes, list):
                raise RuntimeError("Leitor OCR retornou Echoes em formato inválido.")
            echoes: list[dict[str, object]] = []
            for raw_echo in raw_echoes:
                if not isinstance(raw_echo, dict) or any(
                    not isinstance(key, str) for key in raw_echo
                ):
                    raise RuntimeError(
                        "Leitor OCR retornou Echoes em formato inválido."
                    )
                echoes.append(raw_echo)
            if detected_id is not None and detected_id != self.target_id:
                raise ImageCharacterMismatchError(
                    detected_id, self.target_id
                )
            self.status.emit("Finalizando atributos base...")
            self.progress.emit(100)
            import_result: ImageImportResult = {
                "stats": stats,
                "character_id": detected_id,
                "echoes": echoes,
            }
            self.finished.emit(import_result)
        except Exception as error:  # pylint: disable=broad-except
            self.failed.emit(error)
        finally:
            active_process = self._process
            if active_process is not None:
                self._finish_process(active_process)
