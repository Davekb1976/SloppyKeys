"""Icon glyphs from Segoe Fluent Icons.

Ships with Windows, so this needs no SVG renderer or image assets. These are a
vector icon font (not emoji): crisp at any size and consistent with the app's
Windows-only target.

The one exception is `github_icon`: Segoe Fluent has no GitHub mark, and the mark is
the whole point of that button. It is drawn from inline path data through QtSvg rather
than shipped as a PNG, so it stays crisp and `images/` keeps holding only templates.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PLAY = "\uE768"
GRID = "\uE80A"
SETTINGS = "\uE713"
MONITOR = "\uE7F4"
SAVE = "\uE74E"
REFRESH = "\uE72C"
TRASH = "\uE74D"
CROSSHAIR = "\uE1E3"
IMAGE = "\uEB9F"
MINIMIZE = "\uE921"
CLOSE = "\uE8BB"
LINK = "\uE71B"
PLUS = "\uE710"
UP = "\uE74A"
DOWN = "\uE74B"
COPY = "\uE8C8"
UNDO = "\uE7A7"
# Segoe Fluent's "Rename" glyph, which is the pencil-over-a-label the Explorer ribbon uses.
RENAME = "\uE8AC"

# GitHub's own mark, single path, 24x24 viewBox. `fill` is substituted so the icon can be
# tinted to whatever the surrounding text colour is.
_GITHUB_PATH = (
    "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577"
    " 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7"
    " 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07"
    " 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466"
    "-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3"
    " 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23"
    " 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805"
    " 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69"
    ".825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"
)


def github_icon(color: str, size: int = 16) -> QIcon:
    """The GitHub mark, tinted `color`, rendered at `size` device pixels."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path fill="{color}" d="{_GITHUB_PATH}"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)
