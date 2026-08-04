from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
            self.layout.addWidget(label)


def page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageTitle")
    return label


def make_status_label(ok: bool, ok_text: str = "Доступно", fail_text: str = "Недоступно") -> QLabel:
    text = ok_text if ok else fail_text
    color = "#4cc36f" if ok else "#e39a22"
    label = QLabel(text)
    label.setStyleSheet(f"color: {color}; font-weight: 700;")
    return label


def button(text: str, primary: bool = False, danger: bool = False) -> QPushButton:
    btn = QPushButton(text)
    if primary:
        btn.setObjectName("PrimaryButton")
    if danger:
        btn.setObjectName("DangerButton")
    return btn


class OperationLog(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["Время", "Уровень", "Операция", "Сообщение"])
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)

    def add(self, level: str, operation: str, message: str) -> None:
        from datetime import datetime

        row = self.rowCount()
        self.insertRow(row)
        values = [datetime.now().strftime("%H:%M:%S"), level, operation, message]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            self.setItem(row, column, item)
        self.scrollToBottom()


def toolbar(*widgets: QWidget) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for item in widgets:
        layout.addWidget(item)
    layout.addStretch(1)
    return box

