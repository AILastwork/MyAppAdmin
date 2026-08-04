from __future__ import annotations

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.context import PageContext
from app.ui.widgets import Card, button, page_title


class HistoryPage(QWidget):
    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("История / audit"))

        card = Card("Последние события")
        refresh_btn = button("Обновить", primary=True)
        refresh_btn.clicked.connect(self.refresh)
        card.layout.addWidget(refresh_btn)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Время", "Windows user", "Действие", "Тип", "Объект", "Результат", "Сообщение"])
        self.table.horizontalHeader().setStretchLastSection(True)
        card.layout.addWidget(self.table)
        layout.addWidget(card, 1)
        self.refresh()

    def refresh(self) -> None:
        records = self.context.audit.recent(300)
        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                record.created_at,
                record.windows_user,
                record.action,
                record.object_type,
                record.object_name,
                record.result,
                record.message,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

