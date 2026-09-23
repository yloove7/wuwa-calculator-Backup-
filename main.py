"""Tethys launcher kept at the project root for development and packaging."""

from updater_dialog import executar_verificacao_e_update


if __name__ == "__main__":
    reiniciou = executar_verificacao_e_update()
    if reiniciou:
        raise SystemExit(0)

    from src.wuwa_calculator.app.main import main

    raise SystemExit(main())

