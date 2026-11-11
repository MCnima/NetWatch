"""NetWatch entry point: starts the monitor, the dashboard, the speed overlay and the system-tray icon."""
import ctypes
import sys

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QActionGroup
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from collector import EtwCollector, Monitor
from firewall import Blocker, firewall_enabled
from overlay import Overlay
from ui import Dashboard, fmt_rate, make_icon

OPACITY_CHOICES = (30, 50, 75, 100)


def restart_as_admin():
    """Re-launch this program with a UAC elevation prompt. Returns True if the prompt was accepted."""
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    params = " ".join(f'"{a}"' for a in args)
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1) > 32


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NetWatch")
    icon = make_icon()
    app.setWindowIcon(icon)

    tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not tray_ok)  # with a tray icon, closing the window keeps monitoring

    settings = QSettings("NetWatch", "NetWatch")
    saved = settings.value("overlay_opacity", 100, type=int)
    opacity = min(OPACITY_CHOICES, key=lambda v: abs(v - saved))

    etw = EtwCollector()
    per_app = etw.start()
    monitor = Monitor(etw)
    blocker = Blocker()
    window = Dashboard(blocker)
    window.set_per_app_status(per_app, etw.error)
    overlay = Overlay(opacity / 100)
    overlay_action = None
    auto_shown = [False]  # True while the overlay is up only because the dashboard was closed to the tray

    def set_overlay(on, auto=False):
        overlay.setVisible(on)
        auto_shown[0] = on and auto
        window.set_overlay_checked(on)
        if overlay_action:
            overlay_action.setChecked(on)

    def show_window():
        if auto_shown[0]:
            set_overlay(False)  # the overlay was a stand-in for the hidden dashboard
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def quit_app():
        window.quitting = True
        app.quit()

    def set_opacity(percent):
        overlay.setWindowOpacity(percent / 100)
        settings.setValue("overlay_opacity", percent)

    tray = menu = None
    if tray_ok:
        tray = QSystemTrayIcon(icon, app)
        menu = QMenu()
        menu.addAction("Open dashboard").triggered.connect(show_window)
        overlay_action = menu.addAction("Speed overlay")
        overlay_action.setCheckable(True)
        overlay_action.triggered.connect(lambda on: set_overlay(on))
        opacity_menu = menu.addMenu("Overlay opacity")
        group = QActionGroup(opacity_menu)
        for percent in OPACITY_CHOICES:
            action = opacity_menu.addAction(f"{percent}%")
            action.setCheckable(True)
            action.setChecked(percent == opacity)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, v=percent: set_opacity(v))
        menu.addSeparator()
        menu.addAction("Quit NetWatch").triggered.connect(quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: show_window()
                               if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.setToolTip("NetWatch")
        tray.show()
        window.tray = tray

    def on_update(snap):
        window.update_snapshot(snap)
        overlay.set_speeds(snap.down, snap.up)
        if tray:
            tray.setToolTip(f"NetWatch\n↓ {fmt_rate(snap.down)}   ↑ {fmt_rate(snap.up)}")

    window.restart_admin.connect(lambda: restart_as_admin() and quit_app())
    window.overlay_toggled.connect(lambda on: set_overlay(on))
    window.closed_to_tray.connect(lambda: overlay.isVisible() or set_overlay(True, auto=True))
    monitor.updated.connect(on_update)
    app.aboutToQuit.connect(lambda: (monitor.stop(), etw.stop()))

    # startup checks run in the background: drop blocks whose firewall rules were removed, check the firewall
    window.run_job(blocker.verify, lambda _: window.refresh_tables())
    window.run_job(firewall_enabled, window.set_firewall_state)

    monitor.start()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
