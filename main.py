# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).

from __future__ import annotations
import sys
import traceback
# PyQt imports
from PyQt6.QtWidgets import QApplication, QMessageBox
# local imports
from config import load_config
from ui import MainWindow

def global_exception_handler(exc_type, exc_value, exc_traceback) -> None:
    traceback.print_exception(exc_type, exc_value, exc_traceback)

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        dialog = QMessageBox()
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Unexpected Error")
        dialog.setText("A fatal error occurred and ChronoName needs to close.")
        dialog.setInformativeText(str(exc_value))
        dialog.setDetailedText(error_msg)
        dialog.exec()
    except Exception:
        sys.__excepthook__(exc_type, exc_value, exc_traceback)


def main() -> int:
    sys.excepthook = global_exception_handler
    app = QApplication(sys.argv)
    print("[Main] ChronoName started...")
    try:
        config = load_config()
    except ValueError as exc:
        QMessageBox.critical(None, "ChronoName settings error", str(exc))
        return 1
    print("[Main] Settings loaded...")
    window = MainWindow(config)
    window.show()
    print("[Main] GUI started...")
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())

