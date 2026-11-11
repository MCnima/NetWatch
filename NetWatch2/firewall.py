"""Blocking apps from the network with Windows Firewall rules (netsh advfirewall).

Rules live in Windows itself, so they keep working after NetWatch closes. NetWatch also keeps a small
index file so it can list and remove the blocks it created. Only netsh exit codes are used (never its
text output), because that text is translated on non-English Windows.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading

IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # stops a console window flashing up from the windowed app

# Public address space (everything except private, loopback, link-local and multicast ranges).
# "Internet only" blocking applies the rule to these remote addresses, so the local network keeps working.
PUBLIC_V4 = ("0.0.0.0-9.255.255.255,11.0.0.0-126.255.255.255,128.0.0.0-169.253.255.255,"
             "169.255.0.0-172.15.255.255,172.32.0.0-192.167.255.255,192.169.0.0-223.255.255.255")
PUBLIC_V6 = "2000::/3"

# Blocking these can cut off DNS, Windows Update and most other network access.
CRITICAL = {"svchost.exe", "system", "lsass.exe", "services.exe", "wininit.exe", "winlogon.exe", "csrss.exe"}


def run_netsh(*args):
    """Run `netsh advfirewall firewall <args>` and return (ok, output)."""
    kw = {"encoding": "oem", "errors": "replace"} if IS_WIN else {"text": True}
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", *args], capture_output=True, timeout=30,
                           creationflags=NO_WINDOW, **kw)
    except Exception as exc:
        return False, str(exc)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def firewall_enabled():
    """True if Windows Firewall is on for every profile, False if any is off, None if unknown."""
    if not IS_WIN:
        return None
    cmd = "(Get-NetFirewallProfile | ForEach-Object { [string]$_.Enabled }) -join ','"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        values = [v.strip().lower() for v in r.stdout.split(",") if v.strip()]
    except Exception:
        return None
    return None if not values else "false" not in values


def default_state_path():
    return os.path.join(os.environ.get("PROGRAMDATA") or os.path.expanduser("~"), "NetWatch", "blocks.json")


def rule_name(exe, mode):
    tag = hashlib.sha1(exe.lower().encode("utf-8")).hexdigest()[:8]
    return f"NetWatch block ({mode}) {os.path.basename(exe)} [{tag}]"


class Blocker:
    def __init__(self, state_path=None, runner=None):
        self.path = state_path or default_state_path()
        self._netsh = runner or run_netsh
        self.lock = threading.Lock()
        self.entries = self._load()  # exe.lower() -> {"exe", "mode", "name"}

    # ---- queries (safe to call from the UI thread) ----
    def mode_for(self, exe):
        entry = self.entries.get(exe.lower()) if exe else None
        return entry["mode"] if entry else None

    def entries_list(self):
        return sorted((dict(e) for e in self.entries.values()), key=lambda e: e["exe"].lower())

    # ---- changes (run these off the UI thread: each netsh call takes a moment) ----
    def block(self, exe, mode):
        """Block `exe` ('internet' = public addresses only, 'all' = everything). Returns (ok, error)."""
        if mode not in ("internet", "all"):
            return False, f"unknown mode {mode}"
        with self.lock:
            old = self.entries.get(exe.lower())
            if old and old["mode"] == mode:
                return True, ""
            name = rule_name(exe, mode)
            remotes = [None] if mode == "all" else [PUBLIC_V4, PUBLIC_V6]
            for direction in ("out", "in"):
                for remote in remotes:
                    args = ["add", "rule", f"name={name}", f"dir={direction}", "action=block",
                            f"program={exe}", "enable=yes", "profile=any"]
                    if remote:
                        args.append(f"remoteip={remote}")
                    ok, out = self._netsh(*args)
                    if not ok:
                        self._netsh("delete", "rule", f"name={name}")  # roll back any partial rules
                        return False, out or "netsh failed"
            if old:  # switching mode: drop the previous rules only after the new ones are in place
                self._netsh("delete", "rule", f"name={old['name']}")
            self.entries[exe.lower()] = {"exe": exe, "mode": mode, "name": name}
            self._save()
            return True, ""

    def unblock(self, exe):
        with self.lock:
            return self._unblock(exe)

    def unblock_all(self):
        with self.lock:
            failed = [e["exe"] for e in self.entries_list() if not self._unblock(e["exe"])[0]]
        return (not failed), ("Could not remove: " + ", ".join(failed)) if failed else ""

    def verify(self):
        """Forget blocks whose firewall rules were deleted outside NetWatch."""
        with self.lock:
            gone = [k for k, e in self.entries.items() if not self._netsh("show", "rule", f"name={e['name']}")[0]]
            for k in gone:
                del self.entries[k]
            if gone:
                self._save()
            return bool(gone)

    # ---- internals ----
    def _unblock(self, exe):
        entry = self.entries.get(exe.lower())
        if not entry:
            return True, ""
        ok, out = self._netsh("delete", "rule", f"name={entry['name']}")
        if not ok and self._netsh("show", "rule", f"name={entry['name']}")[0]:
            return False, out or "netsh failed"  # delete failed and the rule is still there
        del self.entries[exe.lower()]
        self._save()
        return True, ""

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return {e["exe"].lower(): e for e in json.load(f)}
        except Exception:
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(list(self.entries.values()), f, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass
