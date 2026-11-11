"""NetWatch user interface: dashboard window, live graph, tables, tray icon."""
from collections import deque

from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygon
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QMainWindow,
                             QPushButton, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from collector import IS_WIN, is_admin

GREEN, BLUE = "#2ecc71", "#3b9eff"
DESC = Qt.SortOrder.DescendingOrder


# ---------- formatting helpers: each returns (display text, sort key) ----------
def fmt_bytes(n):
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def fmt_rate(n):
    return "—" if n is None else fmt_bytes(n) + "/s"


def text(v):
    return str(v), str(v).lower()


def count(n):
    return str(n), n


def size(v):
    return fmt_bytes(v), -1 if v is None else v


def rate(v):
    return fmt_rate(v), -1 if v is None else v


def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1f2933"))
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    p.setBrush(QColor(GREEN))
    p.drawPolygon(QPolygon([QPoint(9, 24), QPoint(31, 24), QPoint(20, 44)]))   # download arrow
    p.setBrush(QColor(BLUE))
    p.drawPolygon(QPolygon([QPoint(33, 40), QPoint(55, 40), QPoint(44, 20)]))  # upload arrow
    p.end()
    return QIcon(pm)


class Graph(QWidget):
    """Rolling 60-second line graph of download (green) and upload (blue) speed."""
    N = 60

    def __init__(self):
        super().__init__()
        self.down = deque([0.0] * self.N, maxlen=self.N)
        self.up = deque([0.0] * self.N, maxlen=self.N)
        self.setMinimumHeight(150)

    def push(self, down, up):
        self.down.append(down)
        self.up.append(up)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        p.setPen(QPen(pal.mid().color(), 1, Qt.PenStyle.DotLine))
        for i in (1, 2, 3):
            p.drawLine(0, h * i // 4, w, h * i // 4)
        peak = max(max(self.down), max(self.up), 10 * 1024.0)
        for series, color in ((self.down, GREEN), (self.up, BLUE)):
            path = QPainterPath()
            for i, v in enumerate(series):
                pt = QPointF(i * (w - 1) / (self.N - 1), h - 4 - (h - 8) * v / peak)
                if i == 0:
                    path.moveTo(pt)
                else:
                    path.lineTo(pt)
            p.setPen(QPen(QColor(color), 2))
            p.drawPath(path)
        p.setPen(pal.text().color())
        p.drawText(6, 14, f"scale: {fmt_rate(peak)}   (last 60 s)")


class Item(QTableWidgetItem):
    def __init__(self):
        super().__init__()
        self.key = ""

    def __lt__(self, other):
        return self.key < other.key


class Table(QTableWidget):
    def __init__(self, headers, sort_col, stretch_col=0):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().hide()
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
        self.setSortingEnabled(True)
        self.sortByColumn(sort_col, DESC)

    def fill(self, rows):
        """rows: list of lists of (display text, sort key)."""
        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (label, key) in enumerate(row):
                item = self.item(r, c)
                if item is None:
                    item = Item()
                    self.setItem(r, c, item)
                item.setText(label)
                item.key = key
                align = Qt.AlignmentFlag.AlignVCenter | (
                    Qt.AlignmentFlag.AlignLeft if isinstance(key, str) else Qt.AlignmentFlag.AlignRight)
                item.setTextAlignment(align)
        self.setSortingEnabled(True)  # re-applies the current sort column/order
        self.setUpdatesEnabled(True)


class Dashboard(QMainWindow):
    restart_admin = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NetWatch — network monitor")
        self.resize(1080, 740)
        self.quitting, self.tray, self._hinted, self.snap = False, None, False, None

        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        # warning banner (shown when per-app tracking is unavailable)
        self.banner = QWidget()
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(0, 0, 0, 0)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setStyleSheet("background:#7a5c00; color:white; padding:6px; border-radius:4px;")
        self.admin_btn = QPushButton("Restart as administrator")
        self.admin_btn.clicked.connect(self.restart_admin)
        row.addWidget(self.banner_text, 1)
        row.addWidget(self.admin_btn)
        self.banner.hide()
        layout.addWidget(self.banner)

        # live speed header
        head = QHBoxLayout()
        self.down_lbl, self.up_lbl, self.session_lbl = QLabel("↓ —"), QLabel("↑ —"), QLabel("")
        for lbl, color in ((self.down_lbl, GREEN), (self.up_lbl, BLUE)):
            lbl.setStyleSheet(f"font-size:26px; font-weight:600; color:{color};")
            head.addWidget(lbl)
            head.addSpacing(24)
        head.addStretch(1)
        head.addWidget(self.session_lbl)
        layout.addLayout(head)

        self.graph = Graph()
        layout.addWidget(self.graph)

        self.apps = Table(["Application", "Upload", "Download", "Sent (session)", "Received (session)",
                           "Connections"], 2)
        self.nics = Table(["Adapter", "Upload", "Download", "Sent (session)", "Received (session)"], 2)
        self.conns = Table(["Application", "PID", "Protocol", "Service", "Local", "Remote", "Host", "State",
                            "Sent", "Received"], 9, stretch_col=6)

        conn_tab = QWidget()
        cl = QVBoxLayout(conn_tab)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by app, IP, host, port…")
        self.filter.setClearButtonEnabled(True)
        self.hide_local = QCheckBox("Hide loopback")
        self.hide_local.setChecked(True)
        bar.addWidget(self.filter, 1)
        bar.addWidget(self.hide_local)
        cl.addLayout(bar)
        cl.addWidget(self.conns)
        self.filter.textChanged.connect(self.refresh_conns)
        self.hide_local.toggled.connect(self.refresh_conns)

        tabs = QTabWidget()
        tabs.addTab(self.apps, "Applications")
        tabs.addTab(conn_tab, "Connections")
        tabs.addTab(self.nics, "Adapters")
        layout.addWidget(tabs, 1)

    def set_per_app_status(self, ok, reason=""):
        self.banner.setVisible(not ok)
        if not ok:
            self.banner_text.setText(f"Per-app and per-connection byte counts are off: {reason}. "
                                     "Adapter speeds and the connection list still work.")
            self.admin_btn.setVisible(IS_WIN and not is_admin())

    def update_snapshot(self, s):
        self.snap = s
        self.down_lbl.setText(f"↓ {fmt_rate(s.down)}")
        self.up_lbl.setText(f"↑ {fmt_rate(s.up)}")
        self.session_lbl.setText(f"Since start:  ↓ {fmt_bytes(s.session_down)}    ↑ {fmt_bytes(s.session_up)}")
        self.graph.push(s.down, s.up)
        self.apps.fill([[text(a[0]), rate(a[1]), rate(a[2]), size(a[3]), size(a[4]), count(a[5])]
                        for a in s.apps])
        self.nics.fill([[text(n[0]), rate(n[1]), rate(n[2]), size(n[3]), size(n[4])] for n in s.adapters])
        self.refresh_conns()
        status = "Per-app tracking: " + (f"on ({s.etw_events:,} events, {s.etw_bad} unparsed)" if s.per_app
                                         else "off")
        self.statusBar().showMessage(status)

    def refresh_conns(self, *_):
        if not self.snap:
            return
        needle, hide = self.filter.text().lower().strip(), self.hide_local.isChecked()
        rows = []
        for c in self.snap.conns:
            if hide and c[5].lstrip("[").startswith(("127.", "::1")):
                continue
            if needle and needle not in " ".join(str(x) for x in c).lower():
                continue
            rows.append([text(c[0]), count(c[1]), text(c[2]), text(c[3]), text(c[4]), text(c[5]),
                         text(c[6]), text(c[7]), size(c[8]), size(c[9])])
        self.conns.fill(rows)

    def closeEvent(self, event):
        if self.quitting or self.tray is None:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._hinted:
            self._hinted = True
            self.tray.showMessage("NetWatch is still running",
                                  "Monitoring continues in the system tray. Right-click the icon to quit.",
                                  QSystemTrayIcon.MessageIcon.Information, 4000)
