"""Opt-in, temporary performance measurements for the running Tethys process."""

from __future__ import annotations

import csv
import ctypes
import mmap
import os
import tempfile
import time
import tracemalloc
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

try:
    import psutil
except ImportError:  # Optional: performance-debug must not add a runtime dependency.
    psutil = None

if TYPE_CHECKING:
    from src.wuwa_calculator.app.window import WuwaQtWindow


class PerformanceDebugMonitor(QObject):
    """Write five-second process samples and startup milestones to a TEMP CSV."""

    SAMPLE_MS = 1000
    WINDOW_SECONDS = 5.0

    def __init__(
        self,
        app: QApplication,
        process_started_at: float,
        output_dir: Path | None = None,
    ) -> None:
        super().__init__(app)
        self.app = app
        self.process_started_at = process_started_at
        self.window: WuwaQtWindow | None = None
        self._home: QWidget | None = None
        self._last_input_at: float | None = None
        self._first_home_paint = False
        self._first_interaction = False
        self._closed = False
        self._owns_tracemalloc = not tracemalloc.is_tracing()
        self._window_state = "startup"
        self._window_started_at = time.perf_counter()
        self._window_cpu_started = self._cpu_seconds()
        if self._owns_tracemalloc:
            tracemalloc.start()

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = output_dir or Path(tempfile.gettempdir())
        self.csv_path = destination / f"Tethys-performance-{stamp}.csv"
        self._file = self.csv_path.open("w", newline="", encoding="utf-8")
        fields: list[str] = [
            "state", "timestamp", "duration_seconds",
            "elapsed_since_process_start_s", "performance_mode",
            "fast_startup", "cpu_percent",
            "rss_mb", "private_mb", "virtual_mb", "threads",
            "python_heap_mb", "python_peak_mb", "widget_count",
        ]
        self._writer = csv.DictWriter(self._file, fieldnames=fields)
        self._writer.writeheader()
        self._write_row("STARTUP:INSTRUMENTATION_READY", 0.0, None)

        self._timer = QTimer(self)
        self._timer.setInterval(self.SAMPLE_MS)
        self._timer.timeout.connect(self._sample)
        self._timer.start()
        self.app.installEventFilter(self)
        self.app.aboutToQuit.connect(self.stop)
        print("[Tethys performance debug] Coleta ativa por janelas de 5 s.")
        print("[Tethys performance debug] CSV:", self.csv_path)
        print("[Tethys performance debug] A Home parada; B Home em uso; C Home em Modo leve.")
        print(
            "[Tethys performance debug] D outra aba; E outra aba leve; "
            "F Frequências com vídeo pausado; G vídeo reproduzindo; "
            "H análise ativa; I vídeo + Modo leve; J aba bloqueada."
        )

    def attach_window(self, window: WuwaQtWindow) -> None:
        self.window = window
        self._home = window._tab_widgets.get(0)
        self._window_state = self._classify_state()
        self._window_started_at = time.perf_counter()
        self._window_cpu_started = self._cpu_seconds()

    def mark(
        self,
        state: str,
        elapsed_since_process_start: float | None = None,
        measure_cpu: bool = True,
    ) -> None:
        """Record a startup milestone with elapsed process time."""
        cpu_percent = self._startup_cpu_percent() if measure_cpu else None
        self._write_row(
            state,
            0.0,
            cpu_percent,
            elapsed_since_process_start=elapsed_since_process_start,
        )

    def _startup_cpu_percent(self) -> float | None:
        elapsed = time.perf_counter() - self.process_started_at
        cpu_elapsed = self._cpu_seconds()
        if cpu_elapsed is None or elapsed <= 0:
            return None
        return cpu_elapsed / elapsed * 100.0

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not self._first_home_paint and watched is self._home:
            if event.type() == QEvent.Type.Paint:
                self._first_home_paint = True
                self._write_row(
                    "STARTUP:FIRST_HOME_PAINT",
                    0.0,
                    self._startup_cpu_percent(),
                )
        if event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
            QEvent.Type.Wheel,
            QEvent.Type.MouseMove,
        }:
            self._last_input_at = time.perf_counter()
            if not self._first_interaction:
                self._first_interaction = True
                self._write_row(
                    "STARTUP:FIRST_USER_INTERACTION",
                    0.0,
                    self._startup_cpu_percent(),
                )
        return super().eventFilter(watched, event)

    def _classify_state(self) -> str:
        window = self.window
        if window is None:
            return "A"
        index = window.tabs.currentIndex()
        light = window.settings.get("performance_mode", False, bool)
        if index == 0:
            if light:
                return "C"
            if self._last_input_at is not None and time.perf_counter() - self._last_input_at <= 5:
                return "B"
            return "A"
        if index != 4:
            return "E" if light else "D"

        multimedia = window._tab_widgets.get(4)
        overlay = getattr(multimedia, "_maintenance_overlay", None)
        if light and overlay is not None and not overlay.isHidden():
            return "J"
        player = getattr(multimedia, "video_player", None)
        panel = getattr(multimedia, "dps_panel", None)
        if light:
            if player is not None and getattr(player, "video_path", ""):
                return "I"
            return "E"
        thread = getattr(panel, "live_thread", None)
        is_running = getattr(thread, "isRunning", None)
        if thread is not None and callable(is_running) and is_running():
            return "H"
        if player is not None and getattr(player, "video_path", ""):
            playback = player.media_player.playbackState()
            if playback == player.media_player.PlaybackState.PlayingState:
                return "G"
            return "F"
        return "D"

    @staticmethod
    def _cpu_seconds() -> float | None:
        if psutil is not None:
            try:
                times = psutil.Process(os.getpid()).cpu_times()
                return float(times.user + times.system)
            except Exception:
                return None
        if os.name != "nt":
            process_times = os.times()
            return float(process_times.user + process_times.system)

        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        get_times = kernel32.GetProcessTimes
        get_times.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ulonglong),
        ]
        get_times.restype = ctypes.c_int
        if get_times(
            kernel32.GetCurrentProcess(),
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return (kernel.value + user.value) / 10_000_000
        return None

    @staticmethod
    def _windows_metrics() -> tuple[float | None, float | None, float | None, int | None]:
        class MemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        memory = MemoryCountersEx()
        memory.cb = ctypes.sizeof(memory)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        get_memory.restype = ctypes.c_int
        current_process = kernel32.GetCurrentProcess()
        rss: float | None = None
        private: float | None = None
        virtual: float | None = None
        if get_memory(current_process, ctypes.byref(memory), memory.cb):
            to_mb = 1024 * 1024
            rss = memory.WorkingSetSize / to_mb
            private = memory.PrivateUsage / to_mb
            virtual_bytes = PerformanceDebugMonitor._windows_virtual_bytes(
                current_process
            )
            if virtual_bytes is not None:
                virtual = virtual_bytes / to_mb
        return rss, private, virtual, PerformanceDebugMonitor._windows_thread_count()

    @staticmethod
    def _windows_virtual_bytes(process: int) -> int | None:
        class VmCounters(ctypes.Structure):
            _fields_ = [
                ("PeakVirtualSize", ctypes.c_size_t),
                ("VirtualSize", ctypes.c_size_t),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = VmCounters()
        return_length = ctypes.c_ulong()
        query = ctypes.windll.ntdll.NtQueryInformationProcess
        query.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        query.restype = ctypes.c_long
        status = query(
            process,
            3,
            ctypes.byref(counters),
            ctypes.sizeof(counters),
            ctypes.byref(return_length),
        )
        return counters.VirtualSize if status == 0 else None

    @staticmethod
    def _windows_thread_count() -> int | None:
        class ThreadEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ThreadID", ctypes.c_ulong),
                ("th32OwnerProcessID", ctypes.c_ulong),
                ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
        kernel32.CreateToolhelp32Snapshot.argtypes = [
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if snapshot in {None, invalid_handle}:
            return None
        entry = ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        current_pid = kernel32.GetCurrentProcessId()
        first = kernel32.Thread32First
        following = kernel32.Thread32Next
        first.argtypes = [ctypes.c_void_p, ctypes.POINTER(ThreadEntry32)]
        following.argtypes = [ctypes.c_void_p, ctypes.POINTER(ThreadEntry32)]
        first.restype = ctypes.c_int
        following.restype = ctypes.c_int
        count = 0
        try:
            has_entry = first(snapshot, ctypes.byref(entry))
            while has_entry:
                if entry.th32OwnerProcessID == current_pid:
                    count += 1
                has_entry = following(snapshot, ctypes.byref(entry))
            return count
        finally:
            kernel32.CloseHandle(snapshot)

    @staticmethod
    def _proc_metrics() -> tuple[float | None, float | None, float | None, int | None]:
        try:
            page_size = mmap.PAGESIZE
            values = Path("/proc/self/statm").read_text(encoding="ascii").split()
            to_mb = 1024 * 1024
            virtual = int(values[0]) * page_size / to_mb
            rss = int(values[1]) * page_size / to_mb
            private: float | None = None
            for line in Path("/proc/self/smaps_rollup").read_text(
                encoding="ascii"
            ).splitlines():
                if line.startswith(("Private_Clean:", "Private_Dirty:", "Private_Hugetlb:")):
                    private = (private or 0.0) + int(line.split()[1]) / 1024
            status = Path("/proc/self/status").read_text(encoding="ascii")
            thread_line = next(
                (line for line in status.splitlines() if line.startswith("Threads:")),
                "",
            )
            threads = int(thread_line.split()[1]) if thread_line else None
            return rss, private, virtual, threads
        except (OSError, ValueError, IndexError):
            return None, None, None, None

    def _metrics(self) -> dict[str, float | int | None]:
        rss: float | None = None
        private: float | None = None
        virtual: float | None = None
        threads: int | None = None
        if psutil is not None:
            try:
                process = psutil.Process(os.getpid())
                memory = process.memory_info()
                rss = memory.rss / (1024 * 1024)
                virtual = memory.vms / (1024 * 1024)
                threads = process.num_threads()
                try:
                    full_memory = process.memory_full_info()
                    private_value = getattr(
                        full_memory,
                        "private",
                        getattr(full_memory, "uss", None),
                    )
                    if private_value is not None:
                        private = float(private_value) / (1024 * 1024)
                except Exception:
                    pass
            except Exception:
                pass
        elif os.name == "nt":
            rss, private, virtual, threads = self._windows_metrics()
        else:
            rss, private, virtual, threads = self._proc_metrics()

        heap, peak = tracemalloc.get_traced_memory()
        return {
            "rss_mb": rss,
            "private_mb": private,
            "virtual_mb": virtual,
            "threads": threads,
            "python_heap_mb": heap / (1024 * 1024),
            "python_peak_mb": peak / (1024 * 1024),
            "widget_count": len(self.app.allWidgets()),
        }

    def _write_row(
        self,
        state: str,
        duration: float,
        cpu_percent: float | None,
        elapsed_since_process_start: float | None = None,
    ) -> None:
        row: dict[str, str | int | float | None] = {
            "state": state,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 3),
            "elapsed_since_process_start_s": round(
                elapsed_since_process_start
                if elapsed_since_process_start is not None
                else time.perf_counter() - self.process_started_at,
                3,
            ),
            "cpu_percent": None if cpu_percent is None else round(cpu_percent, 2),
        }
        if self.window is not None:
            window = self.window
            settings = window.settings
            row.update({
                "performance_mode": settings.get("performance_mode", False, bool),
                "fast_startup": settings.get("fast_startup", False, bool),
            })
        else:
            row.update({
                "performance_mode": None,
                "fast_startup": None,
            })
        row.update(self._metrics())
        self._writer.writerow(row)
        self._file.flush()
        print(
            f"[Tethys performance debug] {state}: "
            f"CPU={row['cpu_percent']}% RSS={row['rss_mb']} MB "
            f"threads={row['threads']} heap={row['python_heap_mb']} MB"
        )

    def _sample(self) -> None:
        if self._closed or self.window is None:
            return
        now = time.perf_counter()
        state = self._classify_state()
        if state != self._window_state:
            self._flush_state(now)
            self._window_state = state
            self._window_started_at = now
            self._window_cpu_started = self._cpu_seconds()
            return
        if now - self._window_started_at >= self.WINDOW_SECONDS:
            self._flush_state(now)
            self._window_started_at = now
            self._window_cpu_started = self._cpu_seconds()

    def _flush_state(self, now: float) -> None:
        duration = max(0.0, now - self._window_started_at)
        cpu_now = self._cpu_seconds()
        cpu_percent = None
        if cpu_now is not None and self._window_cpu_started is not None and duration > 0:
            cpu_percent = (cpu_now - self._window_cpu_started) / duration * 100.0
        if duration > 0:
            self._write_row(self._window_state, duration, cpu_percent)

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._flush_state(time.perf_counter())
        self.app.removeEventFilter(self)
        if self._owns_tracemalloc and tracemalloc.is_tracing():
            tracemalloc.stop()
        self._file.close()
        print("[Tethys performance debug] Coleta encerrada:", self.csv_path)
