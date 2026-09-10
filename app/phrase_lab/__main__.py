import sys
from PySide6.QtWidgets import QApplication
from .appearance import configure_application
from .ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Phrase Lab")
    app.setOrganizationName("Signal Processing Lab")
    configure_application(app)
    window = MainWindow()
    area = app.primaryScreen().availableGeometry()
    window.resize(min(1320, area.width() - 48), min(900, area.height() - 64))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
