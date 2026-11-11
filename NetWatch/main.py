"""NetWatch entry point: starts the monitor, the dashboard and the system-tray icon."""
import ctypes
import sys

from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from collector import EtwCollector, Monitor
from ui import Dashboard, fmt_rate, make_icon


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

    etw = EtwCollector()
    per_app = etw.start()
    monitor = Monitor(etw)
    window = Dashboard()
    window.set_per_app_status(per_app, etw.error)

    def show_window():
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def quit_app():
        window.quitting = True
        app.quit()

    tray = menu = None
    if tray_ok:
        tray = QSystemTrayIcon(icon, app)
        menu = QMenu()
        menu.addAction("Open dashboard").triggered.connect(show_window)
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
        if tray:
            tray.setToolTip(f"NetWatch\n↓ {fmt_rate(snap.down)}   ↑ {fmt_rate(snap.up)}")

    window.restart_admin.connect(lambda: restart_as_admin() and quit_app())
    monitor.updated.connect(on_update)
    app.aboutToQuit.connect(lambda: (monitor.stop(), etw.stop()))

    monitor.start()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
