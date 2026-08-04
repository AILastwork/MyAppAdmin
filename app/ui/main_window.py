from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStyle,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.audit import AuditLogger
from app.config import APP_DISPLAY_NAME, AppConfig
from app.security import current_windows_user, is_current_user_domain_admin
from app.ui.context import PageContext
from app.ui.pages.ad_search import AdSearchPage
from app.ui.pages.create_user import CreateUserPage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.documentation import DocumentationPage
from app.ui.pages.glpi import GlpiPage
from app.ui.pages.history import HistoryPage
from app.ui.pages.printers import PrintersPage
from app.ui.pages.settings import SettingsPage
from app.ui.pages.templates import TemplatesPage
from app.ui.pages.v8i import V8iPage
from app.ui.pages.yandex import YandexPage


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, audit: AuditLogger, config_path: Path) -> None:
        super().__init__()
        self.config = config
        self.audit = audit
        self.config_path = config_path
        self.setWindowTitle(f"{APP_DISPLAY_NAME} {__version__}")
        self.resize(1500, 920)

        self.context = PageContext(
            config=self.config,
            audit=self.audit,
            config_path=self.config_path,
            on_config_changed=self.handle_config_changed,
        )
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(220)
        self.stack = QStackedWidget()
        self.pages: list[QWidget] = []

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self._add_pages()
        self.sidebar.currentRowChanged.connect(self.handle_page_changed)
        self.sidebar.setCurrentRow(0)
        self.statusBar().showMessage(f"{APP_DISPLAY_NAME} {__version__} | Пользователь: {current_windows_user()} | Конфиг: {self.config_path}")

    def _build_sidebar(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel(APP_DISPLAY_NAME)
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 16px; font-weight: 700; padding: 14px; color: #ffffff;")
        layout.addWidget(header)
        layout.addWidget(self.sidebar, 1)

        footer = QLabel(f"{current_windows_user()}\nВерсия {__version__}")
        footer.setStyleSheet("padding: 14px; color: #9eb1bf; border-top: 1px solid #243340;")
        layout.addWidget(footer)
        return wrapper

    def _add_pages(self) -> None:
        page_defs = [
            ("Главная", self.style().standardIcon(QStyle.SP_ComputerIcon), DashboardPage(self.context)),
            ("Создать пользователя", self.style().standardIcon(QStyle.SP_FileDialogNewFolder), CreateUserPage(self.context)),
            ("Поиск AD", self.style().standardIcon(QStyle.SP_FileDialogContentsView), AdSearchPage(self.context)),
            ("Почта Yandex", self._mail_icon(), YandexPage(self.context)),
            ("1C / V8i", self.style().standardIcon(QStyle.SP_DriveHDIcon), V8iPage(self.context)),
            ("Шаблоны баз", self.style().standardIcon(QStyle.SP_FileDialogDetailedView), TemplatesPage(self.context)),
            ("Принтеры", self.style().standardIcon(QStyle.SP_DriveNetIcon), PrintersPage(self.context)),
            ("GLPI", self.style().standardIcon(QStyle.SP_BrowserReload), GlpiPage(self.context)),
            ("История", self._scroll_icon(), HistoryPage(self.context)),
        ]
        if is_current_user_domain_admin():
            page_defs.append(("Настройки", self.style().standardIcon(QStyle.SP_FileDialogInfoView), SettingsPage(self.context)))
        page_defs.append(("Описание программы", self.style().standardIcon(QStyle.SP_DialogHelpButton), DocumentationPage(self.context)))
        for title, icon, page in page_defs:
            item = QListWidgetItem(icon, title)
            self.sidebar.addItem(item)
            self.stack.addWidget(page)
            self.pages.append(page)

    def handle_page_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if 0 <= index < len(self.pages):
            on_activate = getattr(self.pages[index], "on_activate", None)
            if callable(on_activate):
                on_activate()

    def _mail_icon(self) -> QIcon:
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#8edbd1"), 1.8)
        painter.setPen(pen)
        painter.drawRoundedRect(3, 6, 16, 11, 2, 2)
        painter.drawLine(4, 7, 11, 13)
        painter.drawLine(18, 7, 11, 13)
        painter.drawLine(4, 16, 9, 12)
        painter.drawLine(18, 16, 13, 12)
        painter.end()
        return QIcon(pixmap)

    def _scroll_icon(self) -> QIcon:
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        outline = QPen(QColor("#d3ad63"), 1.5)
        inner = QPen(QColor("#7b5a2b"), 1.1)
        painter.setPen(outline)
        painter.setBrush(QColor("#f0d39a"))
        painter.drawRoundedRect(5, 5, 12, 12, 3, 3)
        painter.drawEllipse(3, 4, 7, 7)
        painter.drawEllipse(12, 11, 7, 7)

        painter.setPen(inner)
        painter.drawLine(8, 8, 14, 8)
        painter.drawLine(8, 11, 13, 11)
        painter.drawLine(8, 14, 12, 14)
        painter.end()
        return QIcon(pixmap)

    def handle_config_changed(self) -> None:
        from app.ui.theme import apply_theme

        self.config.save(self.config_path)
        app = QApplication.instance()
        if app:
            apply_theme(app, self.config.app_theme)
        self.audit.log("config_save", object_type="config", object_name=str(self.config_path), message="Настройки сохранены")
        self.statusBar().showMessage(f"{APP_DISPLAY_NAME} {__version__} | Настройки сохранены: {self.config_path}")
        for page in self.pages:
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()

    def closeEvent(self, event) -> None:
        active_pages = [
            page
            for page in self.pages
            if callable(getattr(page, "has_active_operation", None))
            and page.has_active_operation()
        ]
        if active_pages:
            answer = QMessageBox.question(
                self,
                "Операция ещё выполняется",
                "Сейчас выполняется добавление в адресную книгу принтера.\n\n"
                "При закрытии операция будет отменена, а дочерний процесс остановлен. "
                "Закрыть приложение?",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            stopped = all(page.cancel_active_operation() for page in active_pages)
            if not stopped:
                QMessageBox.warning(
                    self,
                    "Не удалось закрыть приложение",
                    "Дочерний процесс ещё завершается. Подождите несколько секунд и повторите закрытие.",
                )
                event.ignore()
                return
        super().closeEvent(event)
