"""Public import location for the native capture worker.

The worker implementation still lives beside the DPS analysis primitives so
its existing OCR/state-machine dependencies remain local and acyclic. This
module is the stable capture-package entry point used by new code.
"""

from src.wuwa_calculator.app.dps_simulation_panel import WorkerCapturaNativa

__all__ = ["WorkerCapturaNativa"]
