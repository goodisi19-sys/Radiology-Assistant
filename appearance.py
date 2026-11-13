"""Graphite chrome, teal accents and a consistently light clinical workspace."""
STYLE = '''
QMainWindow { background:#26343c; }
QWidget { background:#f4f7f8; color:#182b34; }
QMenuBar, QToolBar, QStatusBar { background:#26343c; color:#edf6f7; border:0; }
QMenuBar { padding:3px 8px; }
QMenuBar::item { background:transparent; padding:6px 12px; }
QMenuBar::item:selected { background:#3b5059; color:white; }
QMenu { background:white; color:#182b34; border:1px solid #b5c9cd; padding:5px; }
QMenu::item { padding:7px 24px; }
QMenu::item:selected { background:#d2efeb; color:#123e3b; }
QMenu::item:disabled { color:#64777e; }
QToolBar { padding:6px 10px; spacing:5px; }
QToolBar#formatBar { background:#eef3f5; border-bottom:1px solid #c3d1d6; }
QToolBar QToolButton { background:transparent; color:#edf6f7; padding:7px 10px; border:1px solid transparent; border-radius:5px; }
QToolBar QToolButton:hover { background:#3b5059; border-color:#58747d; }
QToolBar QToolButton:pressed, QToolBar QToolButton:checked { background:#087f79; color:white; }
QToolBar QToolButton:disabled { color:#9cabb0; }
QToolBar#formatBar QToolButton { color:#213842; }
QToolBar#formatBar QToolButton:hover, QToolBar#formatBar QToolButton:checked { background:#ccebe7; color:#123e3b; }
QToolBar::separator { background:#658089; width:1px; margin:5px 6px; }
QToolButton#gigaButton { background:#087f79; color:white; border:1px solid #32b4a9; font-weight:600; }
QToolButton#gigaButton:hover { background:#066b65; }
QStatusBar { padding:3px 10px; }
QStatusBar QLabel { background:transparent; color:#edf6f7; }
QStatusBar::item { border:0; }
QSplitter::handle { background:#d6e1e5; width:5px; }
QSplitter::handle:hover { background:#0a9188; }
QTabWidget::pane { border:1px solid #c3d3d8; background:#f4f7f8; border-radius:5px; }
QTabBar::tab { background:#e9eff2; color:#354d58; padding:9px 12px; border-bottom:3px solid transparent; }
QTabBar::tab:selected { background:white; color:#086e68; border-bottom:3px solid #0a9188; font-weight:600; }
QTabBar::tab:hover { background:#dfefed; }
QTextEdit, QPlainTextEdit { background:white; color:#182b34; border:1px solid #c3d3d8; border-radius:5px; padding:12px;
 selection-background-color:#c4e9e4; selection-color:#123e3b; }
QTextEdit#reportEditor { padding:22px; border-radius:0; }
QLineEdit, QSpinBox, QComboBox { background:white; color:#182b34; border:1px solid #b5c9cd; border-radius:5px; padding:6px;
 selection-background-color:#c4e9e4; selection-color:#123e3b; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color:#087f79; }
QComboBox QAbstractItemView, QAbstractItemView { background:white; color:#182b34; selection-background-color:#c4e9e4; selection-color:#123e3b; }
QListWidget, QTreeWidget { background:white; color:#182b34; alternate-background-color:#f4f8f9; border:1px solid #c3d3d8; border-radius:5px;
 selection-background-color:#c4e9e4; selection-color:#123e3b; outline:0; }
QListWidget::item { padding:8px; border-bottom:1px solid #e5edef; }
QTreeWidget::item { padding:4px 3px; }
QListWidget::item:selected, QTreeWidget::item:selected { background:#c4e9e4; color:#123e3b; }
QPushButton { background:white; color:#213842; border:1px solid #b5c9cd; border-radius:5px; padding:8px 14px; }
QPushButton:hover { background:#e2f2ef; border-color:#39988e; }
QPushButton:pressed { background:#c4e9e4; }
QPushButton:focus { border:2px solid #087f79; padding:7px 13px; }
QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled { background:#e8eff1; color:#64777e; border-color:#c3d3d8; }
QLabel, QCheckBox { color:#213842; }
QCheckBox::indicator { width:16px; height:16px; }
QToolTip { background:#26343c; color:white; border:1px solid #58747d; padding:6px; }
'''

def apply(window):
    window.setStyleSheet(STYLE)
    window.completer.popup().setStyleSheet('QAbstractItemView {background:white;color:#182b34;selection-background-color:#c4e9e4;selection-color:#123e3b;}')
