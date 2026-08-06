"""Macro Tester: a separate window for running individual macro steps.

Each row is one named check with its own Test button, so a step can be verified
in isolation before it is wired into the runner. Tests are supplied by the caller
as (group, name, callable) — the callable returns (ok, message).

This is the harness the real macro steps get built against.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .widgets import LogView


class RegionOverlay(QWidget):
    """Full-Roblox-area overlay for picking a point or dragging a region.

    Positioned exactly over the Roblox client rect, so widget-local coordinates
    equal Roblox client coordinates and the selection is inherently clamped to
    the game area. Being on top and opaque to input, it blocks Roblox until the
    user finishes (release) or cancels (Esc).
    """

    def __init__(self, mode: str, rect: tuple[int, int, int, int], on_done) -> None:
        super().__init__(None)
        self._mode = mode  # "point" | "region"
        self._on_done = on_done
        self._start: QPoint | None = None
        self._cur: QPoint | None = None
        self._w = rect[2]
        self._h = rect[3]

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # The OS cross cursor is several pixels thick and its centre is guesswork, which
        # made it impossible to aim at a specific pixel — the point of this overlay. Hide
        # it and draw a 1px crosshair in paintEvent instead, the way a screenshot tool
        # does, with the exact client coordinate printed beside it.
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setMouseTracking(True)
        self.setGeometry(rect[0], rect[1], rect[2], rect[3])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clamp(self, p: QPoint) -> QPoint:
        return QPoint(max(0, min(p.x(), self._w)), max(0, min(p.y(), self._h)))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._finish(None)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = self._clamp(event.position().toPoint())
            self._cur = self._start
            if self._mode == "point":
                self._finish(("point", self._start.x(), self._start.y()))
            else:
                self.update()

    def mouseMoveEvent(self, event) -> None:
        self._cur = self._clamp(event.position().toPoint())
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._mode == "region" and self._start:
            b = self._clamp(event.position().toPoint())
            self._finish(("region", self._start.x(), self._start.y(), b.x(), b.y()))

    def _finish(self, result) -> None:
        self._on_done(result)
        self.close()

    def paintEvent(self, _event) -> None:
        """Every line here is 1px on purpose — this overlay exists to aim at a pixel.

        `QPen` width 1 with antialiasing off lands on exact pixel boundaries; a width-2 pen
        straddles two and hides the one you meant. The dim wash is kept light so the art
        underneath stays readable while cropping.
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor(0, 0, 0, 70))

        thin = QPen(QColor(theme.PURPLE))
        thin.setWidth(1)

        # Crosshair in both modes, always, so the aim point is visible before the drag
        # starts as well as during it.
        if self._cur is not None:
            guide = QPen(QColor(theme.CYAN))
            guide.setWidth(1)
            p.setPen(guide)
            p.drawLine(0, self._cur.y(), self._w, self._cur.y())
            p.drawLine(self._cur.x(), 0, self._cur.x(), self._h)

        if self._mode == "region" and self._start and self._cur:
            sel = QRect(self._start, self._cur).normalized()
            p.fillRect(sel, QColor(139, 92, 246, 30))
            p.setPen(thin)
            # -1 on width/height: drawRect's stroke sits *outside* the given rect on the
            # far edges, so drawing sel directly paints over the first row/column of
            # pixels you are trying to see.
            p.drawRect(sel.x(), sel.y(), max(0, sel.width() - 1), max(0, sel.height() - 1))

        p.setPen(QPen(QColor(theme.TEXT)))
        if self._cur is not None:
            readout = f"{self._cur.x()}, {self._cur.y()}"
            if self._mode == "region" and self._start:
                sel = QRect(self._start, self._cur).normalized()
                readout = f"{sel.x()},{sel.y()}  {sel.width()}x{sel.height()}"
            # Beside the cursor, flipped when close to an edge so it never runs off.
            tx = self._cur.x() + 10 if self._cur.x() < self._w - 120 else self._cur.x() - 110
            ty = self._cur.y() - 8 if self._cur.y() > 24 else self._cur.y() + 20
            p.fillRect(tx - 4, ty - 13, 108, 17, QColor(0, 0, 0, 170))
            p.drawText(tx, ty, readout)
        hint = (
            "Drag a region · Esc to cancel"
            if self._mode == "region"
            else "Click a point · Esc to cancel"
        )
        p.fillRect(6, 6, 210, 18, QColor(0, 0, 0, 170))
        p.drawText(10, 20, hint)
        p.end()

# (ok, message)
TestResult = tuple[bool, str]
TestFn = Callable[[], TestResult]


class _TaskSignals(QObject):
    done = Signal(bool, str)


class Task(QRunnable):
    """Runs a (ok, message) fn off the UI thread so blocking AHK/sleeps don't
    freeze it. Used by the tester rows and by the F1 run loop in window.py."""

    def __init__(self, fn: TestFn) -> None:
        super().__init__()
        self._fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            ok, message = self._fn()
        except Exception as exc:  # never let a test kill the worker
            ok, message = False, f"raised {type(exc).__name__}: {exc}"
        self.signals.done.emit(bool(ok), str(message))


class TestRow(QFrame):
    def __init__(self, name: str, description: str, run: TestFn, on_log, submit) -> None:
        super().__init__()
        self.setObjectName("testRow")
        self._run = run
        self._on_log = on_log
        self._submit = submit  # submit(fn, on_done) -> bool started
        self._name = name

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(name)
        title.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 700;")
        sub = QLabel(description)
        sub.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        text.addWidget(title)
        text.addWidget(sub)
        row.addLayout(text, 1)

        self._result = QLabel("—")
        self._result.setObjectName("testResult")
        self._result.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        self._result.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._result.setMinimumWidth(150)
        row.addWidget(self._result)

        self._button = QPushButton("Test")
        self._button.setStyleSheet("padding: 2px 8px;")
        self._button.setFixedSize(84, 30)
        self._button.clicked.connect(self._execute)
        row.addWidget(self._button)

    def _execute(self) -> None:
        self._result.setText("running...")
        self._result.setStyleSheet(f"color: {theme.WARN}; font-size: 11px; font-weight: 700;")
        self._button.setEnabled(False)
        if not self._submit(self._run, self._finish):
            self._button.setEnabled(True)
            self._result.setText("busy")
            self._result.setStyleSheet(f"color: {theme.WARN}; font-size: 11px; font-weight: 700;")

    def _finish(self, ok: bool, message: str) -> None:
        self._button.setEnabled(True)
        color = theme.GOOD if ok else theme.BAD
        self._result.setText(("PASS " if ok else "FAIL ") + message)
        self._result.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
        self._on_log(f"[{'PASS' if ok else 'FAIL'}] {self._name}: {message}")


class MacroTesterWindow(QWidget):
    """Standalone window. Kept as a plain QWidget with the Window flag so it
    styles like the rest of the app rather than the OS dialog look."""

    def __init__(
        self,
        tests: list[tuple[str, str, str, TestFn]],
        on_select_image: Callable[[], None],
        on_test_search: Callable[[], TestResult],
        get_image_path: Callable[[], str],
        get_rect: Callable[[], "tuple[int, int, int, int] | None"],
    ) -> None:
        super().__init__(None)
        self._on_select_image = on_select_image
        self._on_test_search = on_test_search
        self._get_image_path = get_image_path
        self._get_rect = get_rect
        self._overlay: RegionOverlay | None = None
        # Serialize tests on one background thread so blocking AHK/sleeps never
        # freeze the UI and two tests can't drive input at once.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._test_busy = False
        self._active_task: _Task | None = None
        self.setObjectName("root")
        self.setWindowTitle("SloppyKeys — Macro Tester")
        # The main window is always-on-top, so a normal window can never appear
        # above it. Match that level, otherwise this opens behind the main UI.
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.resize(680, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(1)
        title = QLabel("Macro Tester")
        title.setObjectName("h1")
        sub = QLabel("Run a single macro step in isolation")
        sub.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        header.addWidget(title)
        header.addWidget(sub)
        root.addLayout(header)

        # Test list, grouped
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(8)

        # COORDS: click the Roblox area to read a client coordinate.
        col.addLayout(_group("COORDS"))
        col.addWidget(self._build_coords())

        # VISION section: the image tester (single source of image-search testing).
        col.addLayout(_group("VISION"))
        col.addWidget(self._build_image_tester())

        current_group = None
        for group, name, description, run in tests:
            if group != current_group:
                current_group = group
                col.addLayout(_group(group))
            col.addWidget(TestRow(name, description, run, self._log, self._submit_test))
        col.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Log
        root.addLayout(_group("TEST LOG"))
        self._log_box = LogView()
        self._log_box.setFixedHeight(130)
        root.addWidget(self._log_box)

        footer = QHBoxLayout()
        clear = QPushButton(f"{icons.TRASH}  Clear Log")
        clear.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        clear.clicked.connect(self._log_box.clear)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.close)
        footer.addWidget(clear)
        footer.addStretch(1)
        footer.addWidget(close)
        root.addLayout(footer)

    # # Coordinate picker
    def _build_coords(self) -> QWidget:
        box = QFrame()
        box.setObjectName("sectionBox")
        col = QVBoxLayout(box)
        col.setContentsMargins(12, 10, 12, 12)
        col.setSpacing(8)

        note = QLabel(
            "Point: click the Roblox area for a client X/Y. "
            "Region: drag from A to B for a rect. Result is copied automatically."
        )
        note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        note.setWordWrap(True)
        col.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(8)
        point_btn = QPushButton(f"{icons.CROSSHAIR}  Pick Point")
        point_btn.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 4px 12px;")
        point_btn.setFixedHeight(30)
        point_btn.clicked.connect(lambda: self._open_overlay("point"))
        region_btn = QPushButton(f"{icons.CROSSHAIR}  Pick Region")
        region_btn.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 4px 12px;")
        region_btn.setFixedHeight(30)
        region_btn.clicked.connect(lambda: self._open_overlay("region"))
        row.addWidget(point_btn)
        row.addWidget(region_btn)
        self._coord_result = QLabel("—")
        self._coord_result.setObjectName("testResult")
        self._coord_result.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px; font-weight: 700;")
        row.addWidget(self._coord_result)
        row.addStretch(1)
        col.addLayout(row)
        return box

    def _open_overlay(self, mode: str) -> None:
        if self._overlay is not None:
            return
        rect = self._get_rect()
        if rect is None:
            self._set_coord_result("Roblox not found", False)
            return
        self._overlay = RegionOverlay(mode, rect, self._on_overlay_done)
        self._overlay.show()

    def _on_overlay_done(self, result) -> None:
        self._overlay = None
        if result is None:
            self._log("Selection cancelled.")
            return
        if result[0] == "point":
            _mode, x, y = result
            text = f"{x}, {y}"
            self._set_coord_result(text, True)
            QApplication.clipboard().setText(text)
            self._log(f"Point copied: {text}")
        else:
            _mode, ax, ay, bx, by = result
            w, h = abs(bx - ax), abs(by - ay)
            self._set_coord_result(f"A {ax},{ay}  B {bx},{by}  ({w}x{h})", True)
            clip = f"{ax}, {ay}, {bx}, {by}"
            QApplication.clipboard().setText(clip)
            self._log(f"Region copied: {clip}  ({w}x{h})")

    def _set_coord_result(self, text: str, ok: bool) -> None:
        color = theme.GOOD if ok else theme.BAD
        self._coord_result.setText(text)
        self._coord_result.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700;")

    # # Image tester
    def _build_image_tester(self) -> QWidget:
        box = QFrame()
        box.setObjectName("sectionBox")
        col = QVBoxLayout(box)
        col.setContentsMargins(12, 10, 12, 12)
        col.setSpacing(8)

        caption = QLabel("Image search in viewport")
        caption.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 700;")
        col.addWidget(caption)

        self._image_path = QLabel(self._get_image_path() or "None")
        self._image_path.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._image_path.setWordWrap(True)
        col.addWidget(self._image_path)

        row = QHBoxLayout()
        row.setSpacing(8)
        select = QPushButton(f"{icons.IMAGE}  Select Image")
        select.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        select.setFixedHeight(28)
        select.clicked.connect(self._select_image)
        test = QPushButton(f"{icons.CROSSHAIR}  Test Search")
        test.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        test.setFixedHeight(28)
        test.clicked.connect(self._test_search)
        row.addWidget(select)
        row.addWidget(test)
        row.addStretch(1)

        self._image_result = QLabel("")
        self._image_result.setObjectName("testResult")
        self._image_result.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        row.addWidget(self._image_result)
        col.addLayout(row)
        return box

    def _select_image(self) -> None:
        self._on_select_image()
        self.refresh_image_path()

    def refresh_image_path(self) -> None:
        self._image_path.setText(self._get_image_path() or "None")

    def _test_search(self) -> None:
        self._image_result.setText("running...")
        self._image_result.setStyleSheet(f"color: {theme.WARN}; font-size: 11px; font-weight: 700;")
        if not self._submit_test(self._on_test_search, self._image_search_done):
            self._image_result.setText("busy")
            self._image_result.setStyleSheet(f"color: {theme.WARN}; font-size: 11px; font-weight: 700;")

    def _image_search_done(self, ok: bool, message: str) -> None:
        color = theme.GOOD if ok else theme.BAD
        self._image_result.setText(("PASS " if ok else "FAIL ") + message)
        self._image_result.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
        self._log(f"[{'PASS' if ok else 'FAIL'}] Image search: {message}")

    def _submit_test(self, fn: TestFn, on_done) -> bool:
        """Run a test on the worker thread. One at a time; returns False if busy."""
        if self._test_busy:
            self._log("A test is already running.")
            return False
        self._test_busy = True
        task = Task(fn)
        # Keep a reference: without it Python can GC the task (and its signals)
        # before the worker emits done, so the result never arrives and the row
        # stays stuck on "running". Manage lifetime ourselves.
        task.setAutoDelete(False)
        self._active_task = task

        def finished(ok: bool, message: str) -> None:
            self._test_busy = False
            self._active_task = None
            on_done(ok, message)

        task.signals.done.connect(finished)  # emitted from worker, delivered on UI thread
        self._pool.start(task)
        return True

    def _log(self, message: str) -> None:
        self._log_box.append_line(message)

    def closeEvent(self, event) -> None:
        if self._overlay is not None:
            self._overlay.close()
        super().closeEvent(event)


def _group(title: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("groupHead")
    line = QFrame()
    line.setObjectName("sep")
    row.addWidget(label)
    row.addWidget(line, 1)
    return row
