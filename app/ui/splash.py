from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPointF, QRectF, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from app import __version__
from app.config import APP_DISPLAY_NAME


class StartupSplash(QWidget):
    MINIMUM_VISIBLE_MS = 6200
    FINAL_HOLD_MS = 900
    FADE_MS = 1100
    FRAME_MS = 16

    def __init__(self) -> None:
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(QSize(1120, 640))
        self.setWindowOpacity(1.0)
        self._phase = 0.0
        self._progress = 5
        self._status = "Инициализирую защищенную среду..."
        self._clock = QElapsedTimer()
        self._clock.start()

        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        available = screen.availableGeometry()
        x = available.x() + (available.width() - self.width()) // 2
        y = available.y() + (available.height() - self.height()) // 2
        self.move(x, y)

    def set_status(self, text: str, progress: int | None = None, *, animate_ms: int = 0) -> None:
        self._status = text
        if progress is not None:
            if animate_ms > 0:
                self._animate_progress(progress, animate_ms)
            else:
                self._progress = max(0, min(100, progress))
        self._flush_events()

    def hold(self, milliseconds: int) -> None:
        self._pump_for(milliseconds)

    def finish(self, window: QWidget | None = None) -> None:
        self.set_status("Синхронизирую панели управления...", 94, animate_ms=520)
        self._pump_until_minimum_visible()
        self.set_status("Готово. Открываю панель управления...", 100, animate_ms=720)
        self._pump_for(self.FINAL_HOLD_MS)
        self._crossfade_to(window)
        self._timer.stop()
        self.hide()
        if window:
            window.setWindowOpacity(1.0)
            window.raise_()
            window.activateWindow()
        self.deleteLater()

    def _animate_progress(self, target: int, duration_ms: int) -> None:
        start = self._progress
        end = max(0, min(100, target))
        if start == end:
            self.update()
            return

        clock = QElapsedTimer()
        clock.start()
        curve = QEasingCurve(QEasingCurve.Type.InOutCubic)
        while clock.elapsed() < duration_ms:
            ratio = min(1.0, clock.elapsed() / max(1, duration_ms))
            eased = curve.valueForProgress(ratio)
            self._progress = int(round(start + (end - start) * eased))
            self._flush_events()
            QThread.msleep(self.FRAME_MS)
        self._progress = end
        self._flush_events()

    def _pump_until_minimum_visible(self) -> None:
        while self._clock.elapsed() < self.MINIMUM_VISIBLE_MS:
            self._flush_events()
            QThread.msleep(self.FRAME_MS)

    def _pump_for(self, milliseconds: int) -> None:
        clock = QElapsedTimer()
        clock.start()
        while clock.elapsed() < milliseconds:
            self._flush_events()
            QThread.msleep(self.FRAME_MS)

    def _crossfade_to(self, window: QWidget | None) -> None:
        if window:
            window.setWindowOpacity(0.0)
            window.show()
            window.raise_()

        clock = QElapsedTimer()
        clock.start()
        curve = QEasingCurve(QEasingCurve.Type.InOutCubic)
        while clock.elapsed() < self.FADE_MS:
            ratio = min(1.0, clock.elapsed() / self.FADE_MS)
            eased = curve.valueForProgress(ratio)
            self.setWindowOpacity(1.0 - eased)
            if window:
                window.setWindowOpacity(eased)
            self._flush_events()
            QThread.msleep(self.FRAME_MS)
        self.setWindowOpacity(0.0)
        if window:
            window.setWindowOpacity(1.0)

    def _flush_events(self) -> None:
        self.update()
        app = QApplication.instance()
        if app:
            app.processEvents()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.0058) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        panel = QRectF(12, 12, self.width() - 24, self.height() - 24)
        self._draw_background(painter, panel)
        self._draw_starfield(painter, panel)
        self._draw_scan_sweep(painter, panel)
        self._draw_header(painter)
        self._draw_network(painter)
        self._draw_progress(painter)

    def _draw_background(self, painter: QPainter, panel: QRectF) -> None:
        shadow = QRectF(panel)
        shadow.translate(0, 9)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawRoundedRect(shadow, 24, 24)

        gradient = QLinearGradient(panel.topLeft(), panel.bottomRight())
        gradient.setColorAt(0.0, QColor("#07131c"))
        gradient.setColorAt(0.45, QColor("#0d1f2b"))
        gradient.setColorAt(1.0, QColor("#161329"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#2f6f86"), 1.4))
        painter.drawRoundedRect(panel, 24, 24)

        grid_pen = QPen(QColor(86, 177, 191, 32), 1)
        painter.setPen(grid_pen)
        for x in range(34, self.width() - 28, 34):
            painter.drawLine(x, 34, x, self.height() - 34)
        for y in range(38, self.height() - 32, 34):
            painter.drawLine(34, y, self.width() - 34, y)

        for point, radius, color in (
            (QPointF(850, 140), 250, QColor(74, 209, 255, 42)),
            (QPointF(1010, 476), 230, QColor(164, 103, 255, 38)),
            (QPointF(270, 430), 260, QColor(54, 226, 186, 32)),
        ):
            glow = QRadialGradient(point, radius)
            glow.setColorAt(0.0, color)
            glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(point, radius, radius)

    def _draw_starfield(self, painter: QPainter, panel: QRectF) -> None:
        painter.setPen(Qt.NoPen)
        for index in range(72):
            x = panel.x() + 28 + ((index * 137) % int(panel.width() - 56))
            y = panel.y() + 34 + ((index * 83) % int(panel.height() - 80))
            pulse = 0.5 + 0.5 * math.sin((self._phase * 0.65 + index * 0.047) * math.tau)
            alpha = int(32 + pulse * 105)
            radius = 0.9 + (index % 4) * 0.45
            painter.setBrush(QColor(150, 235, 255, alpha))
            painter.drawEllipse(QPointF(x, y), radius, radius)

        painter.setPen(QPen(QColor(112, 226, 255, 34), 1))
        for index in range(0, 54, 6):
            start = QPointF(panel.x() + 38 + ((index * 137) % int(panel.width() - 76)), panel.y() + 44 + ((index * 83) % int(panel.height() - 100)))
            end = QPointF(panel.x() + 38 + (((index + 3) * 137) % int(panel.width() - 76)), panel.y() + 44 + (((index + 3) * 83) % int(panel.height() - 100)))
            painter.drawLine(start, end)

    def _draw_scan_sweep(self, painter: QPainter, panel: QRectF) -> None:
        sweep_width = 160
        x = panel.x() - sweep_width + ((panel.width() + sweep_width * 2) * ((self._phase * 0.42) % 1.0))
        sweep = QRectF(x, panel.y() + 8, sweep_width, panel.height() - 16)
        gradient = QLinearGradient(sweep.topLeft(), sweep.topRight())
        gradient.setColorAt(0.0, QColor(90, 245, 255, 0))
        gradient.setColorAt(0.48, QColor(90, 245, 255, 24))
        gradient.setColorAt(0.52, QColor(255, 255, 255, 58))
        gradient.setColorAt(1.0, QColor(90, 245, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(sweep, 18, 18)

    def _draw_header(self, painter: QPainter) -> None:
        painter.setPen(QColor("#dffcff"))
        painter.setFont(QFont("Segoe UI", 31, QFont.Weight.Bold))
        painter.drawText(QRectF(64, 44, 560, 52), Qt.AlignLeft | Qt.AlignVCenter, APP_DISPLAY_NAME)

        painter.setPen(QColor("#72d6cc"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(68, 96, 640, 28),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"версия {__version__} · защищенный запуск без лишних окон",
        )

        badge = QRectF(850, 60, 190, 38)
        painter.setPen(QPen(QColor("#51d3c8"), 1.2))
        painter.setBrush(QColor(12, 36, 45, 210))
        painter.drawRoundedRect(badge, 17, 17)
        painter.setPen(QColor("#c5fff6"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(badge, Qt.AlignCenter, "NETWORK BOOT")

    def _draw_hud(self, painter: QPainter) -> None:
        left = QRectF(64, 140, 206, 46)
        painter.setPen(QPen(QColor("#47e7d2"), 1.1))
        painter.setBrush(QColor(8, 28, 36, 150))
        painter.drawRoundedRect(left, 12, 12)
        painter.setPen(QColor("#aaf9ef"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(left.x() + 14, left.y() + 7, left.width() - 28, 14), Qt.AlignLeft, "Профи-панель Админа")

        painter.setPen(Qt.NoPen)
        for index in range(16):
            height = 5 + int((0.5 + 0.5 * math.sin((self._phase * 0.9 + index * 0.11) * math.tau)) * 14)
            color = QColor(76, 231, 211, 80 + index * 6)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(left.x() + 15 + index * 11, left.bottom() - 10 - height, 5, height), 2, 2)

    def _draw_network(self, painter: QPainter) -> None:
        self._draw_hud(painter)
        hub = QPointF(210, 332)
        nodes = [
            ("AD", "LDAPS", QPointF(610, 190), QColor("#64d7ff")),
            ("FS", "UNC", QPointF(830, 224), QColor("#71f0bd")),
            ("GLPI", "Assets", QPointF(724, 356), QColor("#a590ff")),
            ("Cloud", "Yandex 360", QPointF(916, 402), QColor("#8edbd1")),
            ("MFP", "Kyocera", QPointF(608, 498), QColor("#ffcf7a")),
            ("1C", "IBASE", QPointF(366, 504), QColor("#c4ff7a")),
        ]

        paths = [self._signal_path(hub, point, index) for index, (_title, _sub, point, _color) in enumerate(nodes)]
        for index, path in enumerate(paths):
            self._draw_signal_path(painter, path, nodes[index][3], index)

        self._draw_datacenter(painter, hub)
        for title, subtitle, point, color in nodes:
            self._draw_node(painter, title, subtitle, point, color)

    def _signal_path(self, start: QPointF, end: QPointF, index: int) -> QPainterPath:
        path = QPainterPath(start)
        bend = -120 if index % 2 == 0 else 116
        control_1 = QPointF(start.x() + 178, start.y() + bend)
        control_2 = QPointF(end.x() - 150, end.y() - bend * 0.45)
        path.cubicTo(control_1, control_2, end)
        return path

    def _draw_signal_path(self, painter: QPainter, path: QPainterPath, color: QColor, index: int) -> None:
        painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 58), 2.2))
        painter.drawPath(path)

        glow = QColor(color)
        glow.setAlpha(170)
        painter.setPen(QPen(glow, 1.5))
        for offset in (0.0, 0.31, 0.62):
            t = (self._phase * (0.72 + index * 0.02) + offset + index * 0.071) % 1.0
            eased = QEasingCurve(QEasingCurve.Type.InOutSine).valueForProgress(t)
            point = path.pointAtPercent(eased)
            radius = 4.8 + 1.7 * math.sin((self._phase + offset) * math.tau)
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 220))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(point, radius, radius)
            halo = QColor(color)
            halo.setAlpha(55)
            painter.setBrush(halo)
            painter.drawEllipse(point, radius + 6.5, radius + 6.5)

    def _draw_datacenter(self, painter: QPainter, center: QPointF) -> None:
        rack = QRectF(center.x() - 96, center.y() - 110, 192, 220)
        painter.setPen(QPen(QColor("#75f0ff"), 1.3))
        painter.setBrush(QColor(10, 25, 35, 230))
        painter.drawRoundedRect(rack, 16, 16)

        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.setPen(QColor("#bdfaff"))
        painter.drawText(QRectF(rack.x(), rack.y() + 10, rack.width(), 20), Qt.AlignCenter, "DATA CENTER")

        for row in range(5):
            y = rack.y() + 50 + row * 30
            slot = QRectF(rack.x() + 18, y, rack.width() - 36, 15)
            painter.setPen(QPen(QColor("#2d6b7a"), 1))
            painter.setBrush(QColor(13, 39, 51, 235))
            painter.drawRoundedRect(slot, 5, 5)
            for index in range(4):
                pulse = (self._phase + row * 0.13 + index * 0.08) % 1.0
                color = QColor("#4affdf") if pulse < 0.5 else QColor("#597b86")
                painter.setBrush(color)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(slot.x() + 14 + index * 17, slot.center().y()), 2.4, 2.4)

        painter.setPen(QPen(QColor("#5ad7ff"), 1.1))
        painter.setBrush(Qt.NoBrush)
        for radius in (100, 121):
            alpha = int(55 + 35 * math.sin((self._phase + radius / 200) * math.tau))
            pen_color = QColor(90, 215, 255, alpha)
            painter.setPen(QPen(pen_color, 1.1))
            painter.drawEllipse(center, radius + 18, radius + 18)

    def _draw_node(self, painter: QPainter, title: str, subtitle: str, center: QPointF, color: QColor) -> None:
        radius = 58
        pulse = 0.5 + 0.5 * math.sin((self._phase + center.x() / 900) * math.tau)
        self._draw_node_orbits(painter, center, radius, color)
        halo = QColor(color)
        halo.setAlpha(int(36 + pulse * 50))
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(center, radius + 10, radius + 10)

        painter.setPen(QPen(color, 1.5))
        painter.setBrush(QColor(9, 25, 34, 235))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QColor("#efffff"))
        painter.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        painter.drawText(QRectF(center.x() - 54, center.y() - 31, 108, 30), Qt.AlignCenter, title)
        painter.setPen(QColor(color.red(), color.green(), color.blue(), 230))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.drawText(QRectF(center.x() - 58, center.y() + 7, 116, 24), Qt.AlignCenter, subtitle)

    def _draw_node_orbits(self, painter: QPainter, center: QPointF, radius: int, color: QColor) -> None:
        painter.setBrush(Qt.NoBrush)
        for ring_index, ring_radius in enumerate((radius + 18, radius + 31)):
            alpha = 44 if ring_index == 0 else 24
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), alpha), 1.1))
            painter.drawEllipse(center, ring_radius, ring_radius)

        for spark_index in range(2):
            angle = (self._phase * math.tau * (0.34 + spark_index * 0.12)) + spark_index * math.pi
            ring_radius = radius + 24 + spark_index * 8
            point = QPointF(center.x() + math.cos(angle) * ring_radius, center.y() + math.sin(angle) * ring_radius)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 200))
            painter.drawEllipse(point, 3.2, 3.2)


    def _draw_progress(self, painter: QPainter) -> None:
        painter.setPen(QColor("#d7f7ff"))
        painter.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        painter.drawText(QRectF(72, 548, 976, 26), Qt.AlignLeft | Qt.AlignVCenter, self._status)

        track = QRectF(72, 584, 976, 16)
        painter.setPen(QPen(QColor("#315365"), 1))
        painter.setBrush(QColor(6, 16, 22, 235))
        painter.drawRoundedRect(track, 7, 7)

        width = track.width() * self._progress / 100
        if width > 0:
            fill = QRectF(track.x(), track.y(), width, track.height())
            gradient = QLinearGradient(fill.topLeft(), fill.topRight())
            gradient.setColorAt(0.0, QColor("#22e0c1"))
            gradient.setColorAt(0.5, QColor("#58c8ff"))
            gradient.setColorAt(1.0, QColor("#b590ff"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill, 7, 7)

        painter.setPen(QColor("#9fdedb"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(72, 604, 976, 22), Qt.AlignRight | Qt.AlignVCenter, f"{self._progress}%")
