"""Light mode QSS stylesheet for the Simple DIY Electronics Inventory application."""

from __future__ import annotations

LIGHT_THEME_QSS = """
/* ── Global ─────────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: #F5F5F7;
    color: #1D1D1F;
    font-size: 13px;
}

/* ── Toolbar ────────────────────────────────────────────── */
QToolBar {
    background-color: #E8E8ED;
    border-bottom: 1px solid #D1D1D6;
    padding: 4px 8px;
    spacing: 6px;
}

QToolBar QToolButton {
    background-color: #FFFFFF;
    border: 1px solid #C7C7CC;
    border-radius: 6px;
    padding: 5px 12px;
    color: #1D1D1F;
}

QToolBar QToolButton:hover {
    background-color: #E8F0FE;
    border-color: #0071E3;
}

QToolBar QToolButton:pressed {
    background-color: #D0E0F7;
}

/* ── Tabs ───────────────────────────────────────────────── */
QTabWidget::pane {
    background-color: #FFFFFF;
    border: 1px solid #D1D1D6;
    border-top: none;
}

QTabBar::tab {
    background-color: #E8E8ED;
    color: #6E6E73;
    border: 1px solid #D1D1D6;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 18px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1D1D1F;
    font-weight: bold;
}

QTabBar::tab:hover:!selected {
    background-color: #F0F0F5;
    color: #1D1D1F;
}

/* ── Tables ─────────────────────────────────────────────── */
QTableView, QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F5F5FA;
    border: 1px solid #D1D1D6;
    gridline-color: #E5E5EA;
    selection-background-color: #0071E3;
    selection-color: #FFFFFF;
}

QTableView::item, QTableWidget::item {
    padding: 4px 6px;
    color: #1D1D1F;
}

QTableView::item:selected, QTableWidget::item:selected {
    background-color: #0071E3;
    color: #FFFFFF;
}

QTableView::item:selected:hover, QTableWidget::item:selected:hover {
    background-color: #005BB5;
    color: #FFFFFF;
}

QHeaderView::section {
    background-color: #F0F0F5;
    color: #3A3A3C;
    border: none;
    border-bottom: 1px solid #D1D1D6;
    border-right: 1px solid #E5E5EA;
    padding: 5px 8px;
    font-weight: 600;
}

/* ── Group Boxes ────────────────────────────────────────── */
QGroupBox {
    font-weight: bold;
    color: #1D1D1F;
    border: 1px solid #D1D1D6;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #0071E3;
}

/* ── Buttons ────────────────────────────────────────────── */
QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #C7C7CC;
    border-radius: 6px;
    padding: 5px 14px;
    color: #1D1D1F;
    min-height: 22px;
}

QPushButton:hover {
    background-color: #E8F0FE;
    border-color: #0071E3;
}

QPushButton:pressed {
    background-color: #D0E0F7;
}

QPushButton:disabled {
    background-color: #F0F0F5;
    color: #AEAEB2;
    border-color: #E5E5EA;
}

/* ── Line Edits / Search ────────────────────────────────── */
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #C7C7CC;
    border-radius: 6px;
    padding: 5px 10px;
    color: #1D1D1F;
    selection-background-color: #0071E3;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border: 2px solid #0071E3;
    padding: 4px 9px;
}

/* ── Text Edits (notes, log) ────────────────────────────── */
QTextEdit, QPlainTextEdit {
    background-color: #FFFFFF;
    border: 1px solid #D1D1D6;
    border-radius: 4px;
    color: #1D1D1F;
    padding: 4px;
}

QPlainTextEdit {
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    font-size: 12px;
}

/* ── List Views ─────────────────────────────────────────── */
QListView, QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #D1D1D6;
    border-radius: 4px;
    selection-background-color: #0071E3;
    selection-color: #FFFFFF;
}

QListView::item, QListWidget::item {
    padding: 4px 8px;
}

QListView::item:hover, QListWidget::item:hover {
    background-color: #F0F0F5;
    color: #1D1D1F;
}

QListView::item:selected, QListWidget::item:selected {
    background-color: #0071E3;
    color: #FFFFFF;
}

QListView::item:selected:hover, QListWidget::item:selected:hover {
    background-color: #005BB5;
    color: #FFFFFF;
}

/* ── Dock Widgets ───────────────────────────────────────── */
QDockWidget {
    titlebar-close-icon: none;
    color: #1D1D1F;
}

QDockWidget::title {
    background-color: #E8E8ED;
    border: 1px solid #D1D1D6;
    padding: 5px 8px;
    text-align: left;
    font-weight: bold;
}

/* ── Splitter ───────────────────────────────────────────── */
QSplitter::handle {
    background-color: #D1D1D6;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ── Status Bar ─────────────────────────────────────────── */
QStatusBar {
    background-color: #E8E8ED;
    border-top: 1px solid #D1D1D6;
    color: #6E6E73;
    font-size: 12px;
}

/* ── Scroll Bars ────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #F5F5F7;
    width: 12px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #C7C7CC;
    border-radius: 5px;
    min-height: 24px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #AEAEB2;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #F5F5F7;
    height: 12px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #C7C7CC;
    border-radius: 5px;
    min-width: 24px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #AEAEB2;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── Spin Boxes ─────────────────────────────────────────── */
QSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #C7C7CC;
    border-radius: 4px;
    padding: 2px 6px;
}

QSpinBox:focus {
    border: 2px solid #0071E3;
}

/* ── Labels ─────────────────────────────────────────────── */
QLabel {
    background-color: transparent;
    color: #1D1D1F;
}

/* ── Message Boxes ──────────────────────────────────────── */
QMessageBox {
    background-color: #F5F5F7;
}

/* ── Input Dialogs ──────────────────────────────────────── */
QInputDialog {
    background-color: #F5F5F7;
}

/* ── Tooltips ───────────────────────────────────────────── */
QToolTip {
    background-color: #1D1D1F;
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
"""
