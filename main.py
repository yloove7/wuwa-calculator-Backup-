"""Tethys launcher kept at the project root for development and packaging."""

from updater import verificar_e_atualizar


if __name__ == "__main__":
    verificar_e_atualizar()
    from src.wuwa_calculator.app.main import main

    raise SystemExit(main())

