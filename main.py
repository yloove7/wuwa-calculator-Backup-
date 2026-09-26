"""Tethys launcher kept at the project root for development and packaging."""

import os
import sys


def _toggle_dev_in_running_instance() -> int:
    from src.wuwa_calculator.app.dev_ipc import send_dev_toggle

    enabled = send_dev_toggle()
    if enabled is not None:
        state = "ativado" if enabled else "desativado"
        print(f"MODO DEV {state}.")
        return 0
    print("Tethys não está em execução.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--dev"]:
        raise SystemExit(_toggle_dev_in_running_instance())

    if "--performance-debug" in sys.argv:
        import time

        sys.argv.remove("--performance-debug")
        os.environ["TETHYS_PERFORMANCE_DEBUG"] = "1"
        os.environ["TETHYS_PERFORMANCE_START_TIME"] = str(time.perf_counter())

    from updater_dialog import executar_verificacao_e_update

    reiniciou = executar_verificacao_e_update()
    if reiniciou:
        raise SystemExit(0)

    from src.wuwa_calculator.app.main import main

    raise SystemExit(main())
else:
    from updater_dialog import executar_verificacao_e_update
