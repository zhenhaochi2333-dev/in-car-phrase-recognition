"""Shared desktop styling and local vector icons; no audio or network usage."""
import os
from pathlib import Path
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


STYLE = """
QMainWindow, QDialog { background: #f5f7fb; }
QWidget { color: #24324a; font-family: 'Microsoft YaHei'; font-size: 13px; }
QWidget#shell, QScrollArea, QScrollArea > QWidget > QWidget { background: #f5f7fb; }
QScrollArea { border: none; }
QFrame#sidebar { background: #ffffff; border-right: 1px solid #e6ebf3; }
QFrame#card { background: #ffffff; border: 1px solid #e5eaf2; border-radius: 16px; }
QFrame#resultCard { background: #ffffff; border: 1px solid #e1e8f4; border-radius: 18px; }
QFrame#softPanel { background: #f3f6fc; border: none; border-radius: 12px; }
QFrame#footer { background: #ffffff; border-top: 1px solid #e6ebf3; }
QFrame#divider { background: #e9edf4; border: none; max-height: 1px; }
QLabel { background: transparent; border: none; }
QLabel#brand { color: #1f2e48; font-size: 24px; font-weight: 700; }
QLabel#eyebrow { color: #8994a8; font-size: 10px; letter-spacing: 2px; }
QLabel#pageTitle { color: #1f2d46; font-size: 27px; font-weight: 700; }
QLabel#sectionTitle { color: #23324d; font-size: 16px; font-weight: 600; }
QLabel#subtle { color: #7a879b; font-size: 12px; }
QLabel#fieldLabel { color: #52627a; font-size: 12px; }
QLabel#result { color: #1b2d4e; font-size: 30px; font-weight: 600; }
QLabel#metric { color: #334560; font-size: 14px; font-weight: 600; }
QLabel#emptyTitle { color: #53647d; font-size: 16px; font-weight: 600; }
QLabel#pill { background: #edf3ff; color: #4268b7; border-radius: 11px; padding: 5px 11px; font-size: 11px; }
QLabel#pill[tone="neutral"] { background: #f0f3f8; color: #748198; }
QLabel#pill[tone="green"] { background: #eaf6f1; color: #2c7a60; }
QLabel#pill[tone="amber"] { background: #fff5e5; color: #986b24; }
QLabel#pill[tone="red"] { background: #fceeee; color: #b45151; }
QLabel#micDisc { background: #edf3ff; border: 1px solid #e2ebff; border-radius: 36px; }
QLabel#logoDisc { background: #3567e8; border-radius: 12px; }
QPushButton { background: white; color: #53637d; border: 1px solid #dde4ef; border-radius: 8px; padding: 8px 14px; font-weight: 500; }
QPushButton:hover { background: #f4f7fd; border-color: #bdcce5; }
QPushButton:pressed { background: #eaf0fb; }
QPushButton:focus { border-color: #698cf0; }
QPushButton:disabled { color: #a7b1c1; background: #f8f9fc; border-color: #e9edf4; }
QPushButton#primary { color: white; background: #3567e8; border: 1px solid #3567e8; font-weight: 600; }
QPushButton#primary:hover { background: #2b58d0; border-color: #2b58d0; }
QPushButton#primary:pressed { background: #234cb8; }
QPushButton#primary:disabled { background: #b4c6f2; border-color: #b4c6f2; color: #ffffff; }
QPushButton#quiet { background: transparent; border-color: transparent; color: #728198; padding: 6px 9px; }
QPushButton#quiet:hover { background: #edf2fa; color: #3567e8; }
QPushButton#quiet:disabled { color: #b1bac8; }
QPushButton#danger:hover { background: #fff1f1; color: #b04e4e; border-color: #efd1d1; }
QPushButton#nav { text-align: left; background: transparent; border: none; border-radius: 10px; color: #73819a; padding: 13px 14px; font-size: 14px; }
QPushButton#nav:hover { background: #f5f7fc; }
QPushButton#nav:checked { background: #edf3ff; color: #3567e8; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #ffffff; color: #35445e; border: 1px solid #dfe6f1; border-radius: 8px; padding: 9px 11px; selection-background-color: #dce8ff; selection-color: #24479b; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #7597ef; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { background: #f7f9fc; color: #a0aabb; }
QLineEdit#search { background: #f7f9fd; border-color: #e8edf6; }
QComboBox { padding-right: 22px; }
QComboBox::drop-down { width: 23px; border: none; }
QComboBox::down-arrow { image: url("@down"); width: 12px; height: 8px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #dfe6f1; selection-background-color: #edf3ff; selection-color: #3567e8; padding: 5px; outline: 0; }
QCheckBox { spacing: 9px; background: transparent; color: #415370; }
QCheckBox::indicator, QTableView::indicator { width: 16px; height: 16px; background: white; border: 1px solid #cbd6e7; border-radius: 4px; }
QCheckBox::indicator:checked, QTableView::indicator:checked { background: #3567e8; border-color: #3567e8; image: url("@check"); }
QCheckBox::indicator:disabled, QTableView::indicator:disabled { background: #f0f3f9; border-color: #dce3ed; }
QCheckBox::indicator:checked:disabled, QTableView::indicator:checked:disabled { background: #b4c6f2; border-color: #b4c6f2; }
QSpinBox, QDoubleSpinBox { padding-right: 29px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 24px; border-left: 1px solid #e6ebf4; border-bottom: 1px solid #e6ebf4; border-top-right-radius: 8px; background: #f6f8fc; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border-left: 1px solid #e6ebf4; border-bottom-right-radius: 8px; background: #f6f8fc; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@up"); width: 10px; height: 7px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@down"); width: 10px; height: 7px; }
QTableWidget { background: white; alternate-background-color: #fafbfe; border: none; gridline-color: #edf1f7; selection-background-color: #edf3ff; selection-color: #284a94; outline: 0; }
QTableWidget::item { padding: 10px 8px; border-bottom: 1px solid #f0f3f8; }
QTableWidget::item:selected { background: #edf3ff; color: #284a94; }
QHeaderView { background: #f7f9fd; }
QHeaderView::section { background: #f7f9fd; color: #8190a5; font-size: 11px; font-weight: 500; padding: 11px 8px; border: none; border-bottom: 1px solid #eaf0f7; }
QTableCornerButton::section { background: #f7f9fd; border: none; }
QProgressBar { background: #eaf0f9; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #7098f2; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #d6deec; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #b8c6dc; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #263956; color: white; border: none; padding: 7px 10px; }
"""

for _asset in ("check", "down", "up"):
    STYLE = STYLE.replace("@" + _asset, (Path(__file__).parent / "assets" / f"{_asset}.svg").as_posix())

PATHS = {
    "mic": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
    "wave": '<path d="M3 10v4M7.5 6v12M12 3v18M16.5 7v10M21 10v4"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "phrases": '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "settings": '<path d="M4 7h7M15 7h5M4 17h3M11 17h9"/><circle cx="13" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="3"/>',
    "refresh": '<path d="M20 7a9 9 0 1 0 .3 9M20 3v5h-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="m16 3 5 5-12 12-6 1 1-6L16 3ZM13 6l5 5"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "upload": '<path d="M12 15V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
    "speaker": '<path d="m3 9 5 0 5-4v14l-5-4H3ZM17 8a6 6 0 0 1 0 8M20 5a10 10 0 0 1 0 14"/>',
    "history": '<path d="M3 11a9 9 0 1 1 2 7M3 5v6h6M12 7v5l3 2"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    "arrow": '<path d="M5 12h14m-5-5 5 5-5 5"/>',
}


def icon(name, color="#7888a1", size=20):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
           f'stroke-linejoin="round">{PATHS[name]}</svg>')
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


def configure_application(app):
    app.setStyle("Fusion")
    # The offscreen Qt platform does not discover Windows fonts automatically.
    # Register the already installed fonts so actual and preview layouts agree.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc"):
        path = fonts / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei", 10))


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False, symbol=None, kind=None):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary or kind:
        widget.setObjectName("primary" if primary else kind)
    if symbol:
        widget.setIcon(icon(symbol, "#ffffff" if primary else "#7888a1"))
        widget.setIconSize(QSize(17, 17))
    widget.clicked.connect(callback)
    return widget


def card(name="card", margins=22):
    widget = QFrame()
    widget.setObjectName(name)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(16)
    return widget, layout


def badge(text, tone="neutral"):
    widget = label(text, "pill")
    set_badge(widget, text, tone)
    return widget


def set_badge(widget, text, tone="neutral"):
    widget.setText(text)
    widget.setProperty("tone", tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def symbol_label(name, size=24, color="#7888a1"):
    widget = label("")
    widget.setPixmap(icon(name, color, size).pixmap(QSize(size, size)))
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return widget


def divider():
    widget = QFrame()
    widget.setObjectName("divider")
    widget.setFixedHeight(1)
    return widget
