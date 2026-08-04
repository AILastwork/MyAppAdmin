from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.security import collect_security_status
from app.ui.context import PageContext
from app.ui.widgets import button, page_title


class DashboardPage(QWidget):
    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self.grid = QGridLayout()
        self.grid.setSpacing(12)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(page_title("Главная"))
        layout.addWidget(self._build_welcome_panel())
        layout.addLayout(self.grid)
        layout.addStretch(1)

        refresh_btn = button("Обновить проверки", primary=True)
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)
        self.refresh()

    def _build_welcome_panel(self) -> QFrame:
        panel = QFrame()
        panel.setProperty("role", "dashboardHero")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(18)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title = QLabel("Центр управления доменом")
        title.setObjectName("HeroTitle")
        subtitle = QLabel("AD, Yandex 360, 1C и МФУ: быстрый контроль перед рабочими операциями")
        subtitle.setObjectName("HeroSubtitle")
        subtitle.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        layout.addLayout(title_col, 1)

        badges = QVBoxLayout()
        badges.setSpacing(6)
        self.hero_user = QLabel()
        self.hero_domain = QLabel()
        for label in [self.hero_user, self.hero_domain]:
            label.setObjectName("HeroBadge")
            label.setAlignment(Qt.AlignCenter)
            badges.addWidget(label)
        layout.addLayout(badges)
        return panel

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        status = collect_security_status(self.context.config)
        self.hero_user.setText(f"Пользователь: {status.windows_user}")
        self.hero_domain.setText(f"Домен: {status.domain or 'не определен'}")

        cards = [
            ("Текущий пользователь", status.windows_user, True),
            ("Домен", status.domain, bool(status.domain)),
            ("Режим выполнения", "Текущий Windows-пользователь", not status.service_mode_enabled),
            ("USERFOLDER", self.context.config.userfolder_root, status.userfolder_available),
            ("Шаблоны 1C", self.context.config.template_dir, status.template_dir_available),
            ("Yandex token-файл", self.context.config.yandex_token_file, status.yandex_token_file_available),
            ("Printers config", self.context.config.printer_config_file, status.printer_config_file_available),
            ("Тема", self.context.config.app_theme, True),
            ("Audit DB", self.context.config.audit_db, True),
        ]
        for index, (title, value, ok) in enumerate(cards):
            card = self._status_card(title, value, ok)
            self.grid.addWidget(card, index // 2, index % 2)

    def _status_card(self, title: str, value: str, ok: bool) -> QFrame:
        card = QFrame()
        card.setProperty("role", "statusOk" if ok else "statusWarn")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        marker = QLabel("✓" if ok else "!")
        marker.setAlignment(Qt.AlignCenter)
        marker.setFixedSize(34, 34)
        marker.setStyleSheet(
            "font-size: 20px; font-weight: 800; border-radius: 17px;"
            + ("background: #1f8a4c; color: #ffffff;" if ok else "background: #9b6a22; color: #ffffff;")
        )
        layout.addWidget(marker)

        text_layout = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700; color: #ffffff;")
        value_label = QLabel(value)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_layout.addWidget(title_label)
        text_layout.addWidget(value_label)
        layout.addLayout(text_layout, 1)
        return card
