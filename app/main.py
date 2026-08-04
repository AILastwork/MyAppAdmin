from __future__ import annotations

import sys

from app import __version__
from app.audit import AuditLogger
from app.config import APP_DISPLAY_NAME, AppConfig, default_config_path


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--kyocera-worker":
        from app.services.printers.kyocera import run_kyocera_worker

        return run_kyocera_worker(sys.argv[2:])

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit(
            "PySide6 не установлен. Установите зависимости командой: python -m pip install -e ."
        ) from exc

    from app.ui.main_window import MainWindow
    from app.ui.splash import StartupSplash
    from app.ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)

    splash = StartupSplash()
    splash.center_on_screen()
    splash.show()
    splash.set_status("Поднимаю защищенную оболочку MyAppAdmin...", 12, animate_ms=360)

    config_path = default_config_path()
    splash.set_status("Читаю локальный профиль и DPAPI-секреты...", 30, animate_ms=560)
    config = AppConfig.load(config_path)
    apply_theme(app, config.app_theme)

    splash.set_status("Открываю локальный журнал аудита...", 46, animate_ms=520)
    audit = AuditLogger(config.audit_db)
    audit.log("app_start", object_type="application", object_name=APP_DISPLAY_NAME, message=f"Приложение запущено, версия {__version__}")

    splash.set_status("Прокладываю маршруты к AD, сетевым папкам, GLPI и МФУ...", 68, animate_ms=780)
    splash.hold(820)
    window = MainWindow(config=config, audit=audit, config_path=config_path)
    splash.set_status("Собираю рабочие панели и боковое меню...", 88, animate_ms=680)
    window.setWindowOpacity(0.0)
    window.show()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
