from __future__ import annotations


def apply_theme(app, theme_name: str = "dark") -> None:
    app.setStyleSheet(THEMES.get((theme_name or "dark").lower(), DARK_QSS))


DARK_QSS = """
QWidget {
    background: #0f171d;
    color: #d8e2ea;
    font-family: "Segoe UI";
    font-size: 13px;
}
QMainWindow, QStackedWidget {
    background: #0b1117;
}
QListWidget#Sidebar {
    background: #101b24;
    border: 0;
    border-right: 1px solid #243340;
    padding: 8px;
}
QListWidget#Sidebar::item {
    min-height: 38px;
    padding: 8px 10px;
    border-radius: 6px;
    icon-size: 18px;
}
QListWidget#Sidebar::item:selected {
    background: #116b68;
    color: #ffffff;
}
QListWidget#Sidebar::item:hover {
    background: #182a36;
}
QLabel#PageTitle {
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
}
QFrame[role="card"] {
    background: #121f29;
    border: 1px solid #293946;
    border-radius: 6px;
}
QFrame[role="statusOk"] {
    background: #10241c;
    border: 1px solid #2e7d54;
    border-radius: 6px;
}
QFrame[role="statusWarn"] {
    background: #2a2114;
    border: 1px solid #9b6a22;
    border-radius: 6px;
}
QFrame[role="dashboardHero"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #172c36, stop:0.55 #13242d, stop:1 #18251f);
    border: 1px solid #365263;
    border-radius: 6px;
}
QLabel#HeroTitle {
    color: #ffffff;
    font-size: 24px;
    font-weight: 800;
}
QLabel#HeroSubtitle {
    color: #aebdca;
    font-size: 13px;
}
QLabel#HeroBadge {
    background: #0e1820;
    border: 1px solid #314655;
    border-radius: 5px;
    padding: 7px 10px;
    color: #d8e2ea;
    font-weight: 700;
}
QLabel#HeroBadge[state="ok"] {
    border-color: #2e8f63;
    color: #baf4d1;
}
QLabel#HeroBadge[state="warn"] {
    border-color: #b9832e;
    color: #ffe0a8;
}
QFrame[role="mailProgress"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10252d, stop:0.5 #13212d, stop:1 #231d2d);
    border: 1px solid #3d6270;
    border-radius: 6px;
}
QLabel#ProgressTitle {
    color: #ffffff;
    font-weight: 800;
}
QLabel#ProgressStatus {
    color: #a8dcd5;
    font-weight: 700;
}
QProgressBar {
    background: #0c151c;
    border: 1px solid #2d4452;
    border-radius: 5px;
    min-height: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #24b39f, stop:0.5 #6fc2ff, stop:1 #b38cff);
    border-radius: 5px;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {
    background: #111b23;
    border: 1px solid #344654;
    border-radius: 4px;
    padding: 6px;
    selection-background-color: #1b7f7a;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #29a3a0;
}
QPushButton {
    background: #172532;
    border: 1px solid #344654;
    border-radius: 5px;
    padding: 7px 12px;
}
QPushButton:hover {
    background: #203547;
}
QPushButton#PrimaryButton {
    background: #147d78;
    border: 1px solid #25aaa2;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#DangerButton {
    background: #3a1820;
    border: 1px solid #954052;
    color: #ffd8df;
}
QTableWidget, QTableView {
    background: #101923;
    border: 1px solid #293946;
    border-radius: 5px;
    gridline-color: #263744;
    alternate-background-color: #15212b;
}
QHeaderView::section {
    background: #1a2833;
    border: 0;
    border-right: 1px solid #304250;
    padding: 7px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: #1a2833;
    border: 0;
    border-right: 1px solid #304250;
    border-bottom: 1px solid #304250;
}
QTextBrowser#DocumentationText {
    background: #0f1921;
    border: 1px solid #293946;
    border-radius: 5px;
    padding: 14px;
    color: #d8e2ea;
}
QTextBrowser#DocumentationText h1 {
    color: #ffffff;
    font-size: 22px;
    margin-bottom: 12px;
}
QTextBrowser#DocumentationText pre, QTextBrowser#DocumentationText code {
    background: #0b1218;
    color: #b9f2e5;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator, QTableView::indicator, QListWidget::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #52697a;
    background: #0e171f;
}
QCheckBox::indicator:checked, QTableView::indicator:checked, QListWidget::indicator:checked {
    background: #1aa39a;
    border: 1px solid #63d7cf;
}
QStatusBar {
    background: #101923;
    border-top: 1px solid #263744;
}
QSplitter::handle {
    background: #263744;
}
"""


MATRIX_QSS = """
QWidget {
    background: #050806;
    color: #c9f7d4;
    font-family: "Cascadia Mono", "Consolas", "Segoe UI";
    font-size: 13px;
}
QMainWindow, QStackedWidget {
    background: #020403;
}
QListWidget#Sidebar {
    background: #07100a;
    border: 0;
    border-right: 1px solid #1f5f34;
    padding: 8px;
}
QListWidget#Sidebar::item {
    min-height: 38px;
    padding: 8px 10px;
    border-radius: 6px;
    icon-size: 18px;
}
QListWidget#Sidebar::item:selected {
    background: #0b6b2c;
    color: #ecfff0;
}
QListWidget#Sidebar::item:hover {
    background: #0d2313;
}
QLabel#PageTitle {
    font-size: 22px;
    font-weight: 700;
    color: #eaffed;
}
QFrame[role="card"] {
    background: #07110b;
    border: 1px solid #1f6e38;
    border-radius: 6px;
}
QFrame[role="statusOk"] {
    background: #06180c;
    border: 1px solid #20b455;
    border-radius: 6px;
}
QFrame[role="statusWarn"] {
    background: #1b1308;
    border: 1px solid #c08a2d;
    border-radius: 6px;
}
QFrame[role="dashboardHero"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #07180d, stop:0.55 #06110a, stop:1 #10150a);
    border: 1px solid #2b8a49;
    border-radius: 6px;
}
QLabel#HeroTitle {
    color: #f2fff5;
    font-size: 24px;
    font-weight: 800;
}
QLabel#HeroSubtitle {
    color: #a8dcb6;
    font-size: 13px;
}
QLabel#HeroBadge {
    background: #020604;
    border: 1px solid #2b7d47;
    border-radius: 5px;
    padding: 7px 10px;
    color: #d9ffe1;
    font-weight: 700;
}
QLabel#HeroBadge[state="ok"] {
    border-color: #35e875;
    color: #dffff0;
}
QLabel#HeroBadge[state="warn"] {
    border-color: #c08a2d;
    color: #ffe0a8;
}
QFrame[role="mailProgress"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06180c, stop:0.5 #07110b, stop:1 #121608);
    border: 1px solid #2c8f4c;
    border-radius: 6px;
}
QLabel#ProgressTitle {
    color: #f2fff5;
    font-weight: 800;
}
QLabel#ProgressStatus {
    color: #8cf2a9;
    font-weight: 700;
}
QProgressBar {
    background: #020604;
    border: 1px solid #24643b;
    border-radius: 5px;
    min-height: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #35e875, stop:0.5 #5bf08a, stop:1 #d6ff6a);
    border-radius: 5px;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {
    background: #020604;
    border: 1px solid #238145;
    border-radius: 4px;
    padding: 6px;
    selection-background-color: #188744;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #5bf08a;
}
QPushButton {
    background: #07170d;
    border: 1px solid #2a7d45;
    border-radius: 5px;
    padding: 7px 12px;
}
QPushButton:hover {
    background: #0c2815;
}
QPushButton#PrimaryButton {
    background: #0d7c35;
    border: 1px solid #5bf08a;
    color: #f2fff5;
    font-weight: 600;
}
QPushButton#DangerButton {
    background: #2a1010;
    border: 1px solid #b54848;
    color: #ffdede;
}
QTableWidget, QTableView {
    background: #020604;
    border: 1px solid #1e6034;
    border-radius: 5px;
    gridline-color: #143d23;
    alternate-background-color: #07110b;
}
QHeaderView::section {
    background: #0a1d10;
    border: 0;
    border-right: 1px solid #245d38;
    padding: 7px;
    font-weight: 600;
}
QCheckBox::indicator, QTableView::indicator, QListWidget::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid #41b866;
    background: #020604;
}
QCheckBox::indicator:checked, QTableView::indicator:checked, QListWidget::indicator:checked {
    background: #35e875;
    border: 1px solid #9effb9;
}
QStatusBar {
    background: #07110b;
    border-top: 1px solid #1f6e38;
}
QSplitter::handle {
    background: #1f6e38;
}
"""


THEMES = {
    "dark": DARK_QSS,
    "matrix": MATRIX_QSS,
}
