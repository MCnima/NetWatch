"""NetWatch user interface: dashboard window, live graph, tables, app-blocking controls."""
import os
import threading
from collections import deque

from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygon
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QMainWindow, QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from collector import IS_WIN, is_admin
from firewall import CRITICAL

GREEN, BLUE = "#2ecc71", "#3b9eff"
DESC, ASC = Qt.SortOrder.DescendingOrder, Qt.SortOrder.AscendingOrder
MODE_LABEL = {"internet": "internet only", "all": "all network"}
STATUS_LABEL = {"internet": "Blocked: internet", "all": "Blocked: all network"}


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
        self.key, self.ident = "", None

    def __lt__(self, other):
        return self.key < other.key


class Table(QTableWidget):
    """Sortable table. Rows carry an `ident` so the selection follows the same app when rows re-sort."""

    def __init__(self, headers, sort_col, stretch_col=0, order=DESC):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().hide()
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
        self.setSortingEnabled(True)
        self.sortByColumn(sort_col, order)

    def selected_ident(self):
        items = self.selectedItems()
        return items[0].ident if items else None

    def fill(self, rows, idents=None):
        """rows: list of lists of (display text, sort key); idents: one hashable id per row."""
        idents = idents or [None] * len(rows)
        keep = self.selected_ident()
        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for r, (row, ident) in enumerate(zip(rows, idents)):
            for c, (label, key) in enumerate(row):
                item = self.item(r, c)
                if item is None:
                    item = Item()
                    self.setItem(r, c, item)
                item.setText(label)
                item.key, item.ident = key, ident
                align = Qt.AlignmentFlag.AlignLeft if isinstance(key, str) else Qt.AlignmentFlag.AlignRight
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | align)
        self.setSortingEnabled(True)  # re-applies the current sort column/order
        if keep is not None:
            for r in range(self.rowCount()):
                if self.item(r, 0).ident == keep:
                    self.selectRow(r)
                    break
        self.setUpdatesEnabled(True)


class Dashboard(QMainWindow):
    restart_admin = pyqtSignal()
    overlay_toggled = pyqtSignal(bool)
    closed_to_tray = pyqtSignal()
    _job_done = pyqtSignal(object)

    def __init__(self, blocker):
        super().__init__()
        self.setWindowTitle("NetWatch — network monitor")
        self.resize(1100, 760)
        self.blocker = blocker
        self.quitting, self.tray, self._hinted, self.snap = False, None, False, None
        self._job_done.connect(lambda payload: payload[0](payload[1]))

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
        self.overlay_btn = QPushButton("Speed overlay")
        self.overlay_btn.setCheckable(True)
        self.overlay_btn.setToolTip("Show a small transparent speed readout in the top-right corner of the screen")
        self.overlay_btn.clicked.connect(self.overlay_toggled)
        head.addWidget(self.overlay_btn)
        head.addSpacing(16)
        head.addWidget(self.session_lbl)
        layout.addLayout(head)

        self.graph = Graph()
        layout.addWidget(self.graph)

        self.apps = Table(["Application", "Status", "Upload", "Download", "Sent (session)",
                           "Received (session)", "Connections"], 3)
        self.nics = Table(["Adapter", "Upload", "Download", "Sent (session)", "Received (session)"], 2)
        self.conns = Table(["Application", "PID", "Protocol", "Service", "Local", "Remote", "Host", "State",
                            "Sent", "Received"], 9, stretch_col=6)
        self.blocked = Table(["Application", "Blocked", "Program"], 0, stretch_col=2, order=ASC)
        for table in (self.apps, self.conns):
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.customContextMenuRequested.connect(lambda pos, t=table: self.table_menu(t, pos))
        self.apps.itemSelectionChanged.connect(self.update_buttons)
        self.blocked.itemSelectionChanged.connect(self.update_buttons)

        # Applications tab: block controls above the table
        apps_tab = QWidget()
        al = QVBoxLayout(apps_tab)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Selected app:"))
        self.btn_net = QPushButton("Block internet")
        self.btn_net.setToolTip("Block the app from the internet; devices on your local network stay reachable")
        self.btn_all = QPushButton("Block all network")
        self.btn_all.setToolTip("Block all incoming and outgoing traffic of the app")
        self.btn_unblock = QPushButton("Unblock")
        self.btn_net.clicked.connect(lambda: self.block_selected("internet"))
        self.btn_all.clicked.connect(lambda: self.block_selected("all"))
        self.btn_unblock.clicked.connect(self.unblock_selected)
        for b in (self.btn_net, self.btn_all, self.btn_unblock):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(QLabel("Tip: right-click any app or connection to block it"))
        al.addLayout(bar)
        al.addWidget(self.apps)

        # Connections tab: filter above the table
        conn_tab = QWidget()
        cl = QVBoxLayout(conn_tab)
        cbar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by app, IP, host, port…")
        self.filter.setClearButtonEnabled(True)
        self.hide_local = QCheckBox("Hide loopback")
        self.hide_local.setChecked(True)
        cbar.addWidget(self.filter, 1)
        cbar.addWidget(self.hide_local)
        cl.addLayout(cbar)
        cl.addWidget(self.conns)
        self.filter.textChanged.connect(self.refresh_conns)
        self.hide_local.toggled.connect(self.refresh_conns)

        # Blocked tab
        blocked_tab = QWidget()
        bl = QVBoxLayout(blocked_tab)
        self.fw_note = QLabel("Windows Firewall looks turned off for at least one network profile. Blocks only "
                              "take effect while the firewall is on for the profile you are connected to.")
        self.fw_note.setWordWrap(True)
        self.fw_note.setStyleSheet("background:#7a5c00; color:white; padding:6px; border-radius:4px;")
        self.fw_note.hide()
        bbar = QHBoxLayout()
        self.btn_unblock_sel = QPushButton("Unblock selected")
        self.btn_unblock_all = QPushButton("Unblock all")
        self.btn_unblock_sel.clicked.connect(self.unblock_from_blocked_tab)
        self.btn_unblock_all.clicked.connect(self.unblock_all)
        bbar.addWidget(self.btn_unblock_sel)
        bbar.addWidget(self.btn_unblock_all)
        bbar.addStretch(1)
        bbar.addWidget(QLabel("Blocks are Windows Firewall rules: they stay active until you unblock them."))
        bl.addWidget(self.fw_note)
        bl.addLayout(bbar)
        bl.addWidget(self.blocked)

        self.tabs = QTabWidget()
        self.tabs.addTab(apps_tab, "Applications")
        self.tabs.addTab(conn_tab, "Connections")
        self.tabs.addTab(self.nics, "Adapters")
        self.tabs.addTab(blocked_tab, "Blocked (0)")
        layout.addWidget(self.tabs, 1)

        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)
        self.update_buttons()

    # ---------- status / banners ----------
    def set_per_app_status(self, ok, reason=""):
        self.banner.setVisible(not ok)
        if not ok:
            self.banner_text.setText(f"Per-app and per-connection byte counts are off: {reason}. "
                                     "Adapter speeds and the connection list still work.")
            self.admin_btn.setVisible(IS_WIN and not is_admin())

    def set_firewall_state(self, enabled):
        self.fw_note.setVisible(enabled is False)

    def set_overlay_checked(self, on):
        self.overlay_btn.blockSignals(True)
        self.overlay_btn.setChecked(on)
        self.overlay_btn.blockSignals(False)

    # ---------- live data ----------
    def update_snapshot(self, s):
        self.snap = s
        self.down_lbl.setText(f"↓ {fmt_rate(s.down)}")
        self.up_lbl.setText(f"↑ {fmt_rate(s.up)}")
        self.session_lbl.setText(f"Since start:  ↓ {fmt_bytes(s.session_down)}    ↑ {fmt_bytes(s.session_up)}")
        self.graph.push(s.down, s.up)
        self.status_lbl.setText("Per-app tracking: " + (f"on ({s.etw_events:,} events, {s.etw_bad} unparsed)"
                                                        if s.per_app else "off"))
        self.refresh_tables()

    def status_of(self, exe):
        return STATUS_LABEL.get(self.blocker.mode_for(exe), "")

    def refresh_tables(self):
        s = self.snap
        if s:
            self.apps.fill([[text(a[0]), text(self.status_of(a[6])), rate(a[1]), rate(a[2]), size(a[3]),
                             size(a[4]), count(a[5])] for a in s.apps], [("app", a[0], a[6]) for a in s.apps])
            self.nics.fill([[text(n[0]), rate(n[1]), rate(n[2]), size(n[3]), size(n[4])] for n in s.adapters])
            self.refresh_conns()
        self.refresh_blocked()
        self.update_buttons()

    def refresh_conns(self, *_):
        if not self.snap:
            return
        needle, hide = self.filter.text().lower().strip(), self.hide_local.isChecked()
        rows, idents = [], []
        for c in self.snap.conns:
            if hide and c[5].lstrip("[").startswith(("127.", "::1")):
                continue
            if needle and needle not in " ".join(str(x) for x in c[:10]).lower():
                continue
            rows.append([text(c[0]), count(c[1]), text(c[2]), text(c[3]), text(c[4]), text(c[5]),
                         text(c[6]), text(c[7]), size(c[8]), size(c[9])])
            idents.append(("conn", c[0], c[10], c[1], c[2], c[5]))
        self.conns.fill(rows, idents)

    def refresh_blocked(self):
        entries = self.blocker.entries_list()
        self.blocked.fill([[text(os.path.basename(e["exe"])), text(MODE_LABEL[e["mode"]]), text(e["exe"])]
                           for e in entries],
                          [("blocked", os.path.basename(e["exe"]), e["exe"]) for e in entries])
        self.tabs.setTabText(3, f"Blocked ({len(entries)})")

    def update_buttons(self):
        ident = self.apps.selected_ident()
        self.btn_net.setEnabled(ident is not None)
        self.btn_all.setEnabled(ident is not None)
        self.btn_unblock.setEnabled(ident is not None and self.blocker.mode_for(ident[2]) is not None)
        self.btn_unblock_sel.setEnabled(self.blocked.selected_ident() is not None)
        self.btn_unblock_all.setEnabled(bool(self.blocker.entries))

    # ---------- blocking ----------
    def run_job(self, fn, then):
        """Run fn() on a worker thread (netsh is slow) and call then(result) back on the UI thread."""
        def work():
            try:
                result = fn()
            except Exception as exc:
                result = (False, str(exc))
            self._job_done.emit((then, result))
        threading.Thread(target=work, daemon=True).start()

    def job_finished(self, result, done_message):
        ok, error = result
        if ok:
            self.statusBar().showMessage(done_message, 8000)
        else:
            QMessageBox.warning(self, "NetWatch", f"Windows Firewall did not accept the change.\n\n{error}")
        self.refresh_tables()

    def table_menu(self, table, pos):
        item = table.itemAt(pos)
        if item is None or item.ident is None:
            return
        ident = item.ident  # captured now: the table refreshes every second
        menu = QMenu(self)
        menu.addAction(ident[1]).setEnabled(False)
        menu.addSeparator()
        menu.addAction("Block internet (keep local network)").triggered.connect(
            lambda: self.request_block(ident, "internet"))
        menu.addAction("Block all network").triggered.connect(lambda: self.request_block(ident, "all"))
        unblock = menu.addAction("Unblock")
        unblock.setEnabled(self.blocker.mode_for(ident[2]) is not None)
        unblock.triggered.connect(lambda: self.request_unblock(ident))
        menu.exec(table.viewport().mapToGlobal(pos))

    def block_selected(self, mode):
        ident = self.apps.selected_ident()
        if ident:
            self.request_block(ident, mode)

    def unblock_selected(self):
        ident = self.apps.selected_ident()
        if ident:
            self.request_unblock(ident)

    def unblock_from_blocked_tab(self):
        ident = self.blocked.selected_ident()
        if ident:
            self.request_unblock(ident)

    def request_block(self, ident, mode):
        name, exe = ident[1], ident[2]
        if not IS_WIN:
            QMessageBox.information(self, "NetWatch", "Blocking uses Windows Firewall, so it only works on Windows.")
            return
        if not exe:
            QMessageBox.warning(self, "NetWatch", f"NetWatch can't read the program path of {name} (it may be a "
                                "protected system process), so it can't be blocked.")
            return
        if not is_admin():
            QMessageBox.warning(self, "NetWatch", "Blocking needs administrator rights. Use “Restart as "
                                "administrator” and try again.")
            return
        if name.lower() in CRITICAL:
            answer = QMessageBox.warning(
                self, "Block a Windows system process?",
                f"{name} hosts core Windows services. Blocking it can cut off DNS, Windows Update and most of "
                "your network access.\n\nBlock it anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.run_job(lambda: self.blocker.block(exe, mode),
                     lambda res: self.job_finished(res, f"Blocked {name} ({MODE_LABEL[mode]})"))

    def request_unblock(self, ident):
        name, exe = ident[1], ident[2]
        if exe:
            self.run_job(lambda: self.blocker.unblock(exe),
                         lambda res: self.job_finished(res, f"Unblocked {name}"))

    def unblock_all(self):
        self.run_job(self.blocker.unblock_all, lambda res: self.job_finished(res, "Removed all NetWatch blocks"))

    # ---------- window behaviour ----------
    def closeEvent(self, event):
        if self.quitting or self.tray is None:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.closed_to_tray.emit()
        if not self._hinted:
            self._hinted = True
            self.tray.showMessage("NetWatch is still running",
                                  "Monitoring continues in the system tray. Right-click the icon to quit.",
                                  QSystemTrayIcon.MessageIcon.Information, 4000)
