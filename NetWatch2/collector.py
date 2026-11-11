"""NetWatch data collection: adapter counters, live connections, per-app bytes (ETW)."""
import ctypes
import queue
import socket
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

import psutil
from PyQt6.QtCore import QThread, pyqtSignal

IS_WIN = sys.platform == "win32"
KERNEL_NETWORK_GUID = "{7DD42A49-5329-4832-8DFD-43D979153A88}"
# Microsoft-Windows-Kernel-Network event ids -> (direction, protocol)
ETW_EVENTS = {10: ("up", "TCP"), 11: ("down", "TCP"), 26: ("up", "TCP"), 27: ("down", "TCP"),
              42: ("up", "UDP"), 43: ("down", "UDP"), 58: ("up", "UDP"), 59: ("down", "UDP")}


def is_admin():
    try:
        return IS_WIN and bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(str(value), 16)


@lru_cache(maxsize=4096)
def service(port, proto):
    try:
        return socket.getservbyport(port, proto.lower())
    except Exception:
        return ""


def endpoint(ip, port):
    return f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"


class Resolver:
    """Background reverse-DNS with a cache (daemon threads so quitting never blocks)."""

    def __init__(self, workers=4):
        self.cache, self.queue = {}, queue.Queue()
        for _ in range(workers):
            threading.Thread(target=self._work, daemon=True).start()

    def get(self, ip):
        if ip not in self.cache:
            self.cache[ip] = ""
            self.queue.put(ip)
        return self.cache[ip]

    def _work(self):
        while True:
            ip = self.queue.get()
            try:
                self.cache[ip] = socket.gethostbyaddr(ip)[0]
            except Exception:
                pass


class EtwCollector:
    """Per-process and per-flow byte counters from the Windows kernel network provider.

    Needs Administrator rights (ETW kernel providers are privileged) and `pip install pywintrace`.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.procs = defaultdict(lambda: [0, 0])  # pid -> [bytes up, bytes down]
        self.flows = {}                            # (pid, proto, remote ip, remote port) -> [up, down, last_seen]
        self.local_ips = set()
        self.events = self.bad = 0
        self.job = None
        self.error = ""

    def start(self):
        if not IS_WIN:
            self.error = "per-app byte counts are only available on Windows"
            return False
        if not is_admin():
            self.error = "NetWatch is not running as administrator"
            return False
        try:
            import etw
            provider = etw.ProviderInfo("Microsoft-Windows-Kernel-Network", etw.GUID(KERNEL_NETWORK_GUID))
            self.job = etw.ETW(providers=[provider], event_callback=self._on_event,
                               event_id_filters=list(ETW_EVENTS))
            self.job.start()
            return True
        except Exception as exc:
            self.job = None
            self.error = f"could not start event tracing ({exc})"
            return False

    def stop(self):
        try:
            if self.job:
                self.job.stop()
        except Exception:
            pass

    def _on_event(self, evt):
        try:
            event_id, data = evt
            direction, proto = ETW_EVENTS[event_id]
            pid = _num(data.get("PID", data.get("EventHeader", {}).get("ProcessId")))
            size = _num(data["size"])
            src, dst = str(data["saddr"]), str(data["daddr"])
            sport, dport = _num(data["sport"]), _num(data["dport"])
        except Exception:
            self.bad += 1
            return
        self.events += 1
        if src in self.local_ips and dst in self.local_ips:
            return  # loopback / same-machine traffic is not network usage
        rip, rport = (dst, dport) if src in self.local_ips else (src, sport)
        idx = 0 if direction == "up" else 1
        now = time.time()
        with self.lock:
            self.procs[pid][idx] += size
            flow = self.flows.setdefault((pid, proto, rip, rport), [0, 0, now])
            flow[idx] += size
            flow[2] = now

    def snapshot(self):
        now = time.time()
        with self.lock:
            for key in [k for k, v in self.flows.items() if now - v[2] > 300]:
                del self.flows[key]
            return ({k: tuple(v) for k, v in self.procs.items()},
                    {k: tuple(v) for k, v in self.flows.items()})


@dataclass
class Snapshot:
    up: float = 0.0          # bytes/s, all active adapters
    down: float = 0.0
    session_up: int = 0      # bytes since NetWatch started
    session_down: int = 0
    adapters: list = field(default_factory=list)  # (name, up/s, down/s, total up, total down)
    apps: list = field(default_factory=list)      # (name, up/s, down/s, total up, total down, connections, exe path)
    conns: list = field(default_factory=list)     # (app, pid, proto, service, local, remote, host, state, up, down, exe path)
    per_app: bool = False
    etw_events: int = 0
    etw_bad: int = 0


class Monitor(QThread):
    """Samples once per second and emits a Snapshot."""
    updated = pyqtSignal(object)

    def __init__(self, etw, parent=None):
        super().__init__(parent)
        self.etw = etw
        self.resolver = Resolver()
        self._halt = threading.Event()
        self._info_cache, self._exe_by_name = {}, {}
        self._prev_ts = None
        self._prev_nic, self._base_nic, self._prev_app = {}, {}, {}

    def stop(self):
        self._halt.set()
        self.wait(3000)

    def run(self):
        while not self._halt.is_set():
            started = time.monotonic()
            try:
                self.updated.emit(self._sample(started))
            except Exception:
                pass
            self._halt.wait(max(0.1, 1.0 - (time.monotonic() - started)))

    def _info(self, pid):
        """(process name, full exe path or "") for a pid, cached."""
        if pid not in self._info_cache:
            try:
                proc = psutil.Process(pid)
                name = proc.name()
                try:
                    exe = proc.exe()
                except Exception:
                    exe = ""
            except Exception:
                name, exe = f"PID {pid}", ""
            self._info_cache[pid] = (name, exe)
            if exe:
                self._exe_by_name.setdefault(name, exe)
        return self._info_cache[pid]

    def _name(self, pid):
        return self._info(pid)[0]

    def _sample(self, now):
        dt = (now - self._prev_ts) if self._prev_ts else None
        self._prev_ts = now
        snap = Snapshot(per_app=self.etw.job is not None, etw_events=self.etw.events, etw_bad=self.etw.bad)

        # --- adapters (works without admin) ---
        self.etw.local_ips = {a.address.split("%")[0] for lst in psutil.net_if_addrs().values() for a in lst}
        stats, nic = psutil.net_if_stats(), {}
        for name, c in psutil.net_io_counters(pernic=True).items():
            st = stats.get(name)
            if st and st.isup and "loopback" not in name.lower() and name != "lo":
                nic[name] = (c.bytes_sent, c.bytes_recv)
        for name, (sent, recv) in nic.items():
            prev_s, prev_r = self._prev_nic.get(name, (sent, recv))
            base_s, base_r = self._base_nic.setdefault(name, (sent, recv))
            up = max(0, sent - prev_s) / dt if dt else 0.0
            down = max(0, recv - prev_r) / dt if dt else 0.0
            snap.adapters.append((name, up, down, sent - base_s, recv - base_r))
            snap.up += up
            snap.down += down
            snap.session_up += sent - base_s
            snap.session_down += recv - base_r
        self._prev_nic = nic

        # --- live connections ---
        try:
            raw = psutil.net_connections(kind="inet")
        except Exception:
            raw = []
        procs, flows = self.etw.snapshot()
        conn_count, seen = defaultdict(int), set()
        for c in raw:
            if not c.raddr or not c.pid or c.status == "TIME_WAIT":
                continue
            proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
            name = self._name(c.pid)
            conn_count[name] += 1
            key = (c.pid, proto, c.raddr.ip, c.raddr.port)
            seen.add(key)
            flow = flows.get(key)
            up, down = (flow[0], flow[1]) if flow else ((0, 0) if snap.per_app else (None, None))
            snap.conns.append((name, c.pid, proto, service(c.raddr.port, proto),
                               endpoint(c.laddr.ip, c.laddr.port), endpoint(c.raddr.ip, c.raddr.port),
                               self.resolver.get(c.raddr.ip), "—" if c.status == "NONE" else c.status, up, down,
                               self._info(c.pid)[1]))
        # Flows seen by ETW in the last 15 s but absent from the socket table (QUIC/UDP, DNS, short-lived TCP)
        recent = time.time() - 15
        for (pid, proto, ip, port), (up, down, last) in flows.items():
            if (pid, proto, ip, port) in seen or last < recent:
                continue
            snap.conns.append((self._name(pid), pid, proto, service(port, proto), "—", endpoint(ip, port),
                               self.resolver.get(ip), "recent", up, down, self._info(pid)[1]))

        # --- per-application totals ---
        if snap.per_app:
            totals = defaultdict(lambda: [0, 0])
            for pid, (up, down) in procs.items():
                name = self._name(pid)
                totals[name][0] += up
                totals[name][1] += down
            for name in set(totals) | set(conn_count):
                up, down = totals[name] if name in totals else (0, 0)
                prev_up, prev_down = self._prev_app.get(name, (0, 0))
                snap.apps.append((name, max(0, up - prev_up) / dt if dt else 0.0,
                                  max(0, down - prev_down) / dt if dt else 0.0, up, down, conn_count.get(name, 0),
                                  self._exe_by_name.get(name, "")))
            self._prev_app = {n: tuple(v) for n, v in totals.items()}
        else:
            snap.apps = [(n, None, None, None, None, k, self._exe_by_name.get(n, "")) for n, k in conn_count.items()]
        return snap
