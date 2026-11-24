# NetWatch 🌐🔍

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-blue.svg)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-green.svg)](https://riverbankcomputing.com/software/pyqt/)

A lightweight, real-time Windows network traffic monitor and firewall control suite built with Python and PyQt6.

NetWatch monitors per-adapter and per-process bandwidth utilizing Windows Event Tracing (ETW) for kernel-level accuracy, tracks active sockets and short-lived UDP/QUIC flows, provides a floating desktop speed overlay, and offers fine-grained Windows Defender Firewall application blocking.

---

## 📂 Repository Structure

This repository includes two editions of the application:

| Edition | Directory | Key Features |
| :--- | :--- | :--- |
| **NetWatch (v1)** | [`NetWatch/`](NetWatch/) | • Real-time traffic graph & session stats<br>• Per-application upload/download bandwidth via ETW<br>• Active connection table with background reverse-DNS<br>• Minimize to system tray with live speed tooltips |
| **NetWatch 2 (v2)** | [`NetWatch2/`](NetWatch2/) | • **All features from v1**, plus:<br>• **Floating Speed Overlay**: Always-on-top HUD with configurable opacity (30%, 50%, 75%, 100%)<br>• **Windows Firewall Blocker**: Block apps completely or restrict to LAN-only (block public internet) via native `netsh advfirewall` rules |

---

## ✨ Features

- **Kernel-Level ETW Tracing:** Captures precise per-process upload and download bytes directly from the `Microsoft-Windows-Kernel-Network` ETW provider.
- **Short-Lived Flow Detection:** Accurately catches ephemeral UDP/QUIC connections and quick DNS requests often missed by traditional socket polling.
- **Background Reverse-DNS:** Multi-threaded hostname resolution that keeps the UI responsive and stutter-free.
- **Floating Desktop HUD (NetWatch 2):** Minimalist, draggable, click-through-ready speed widget that can auto-display when the dashboard is minimized to the tray.
- **Native Firewall Integration (NetWatch 2):**
  - **All Traffic:** Blocks inbound and outbound socket operations for targeted executables.
  - **Internet Only:** Blocks public IPv4/IPv6 ranges while preserving local network/LAN communications.
  - Rules persist in Windows Defender Firewall even if NetWatch is closed.
- **System Tray Integration:** Runs silently in the background, updating dynamic tooltip upload/download speeds.

---

## 🛠️ Prerequisites & Requirements

- **Operating System:** Windows 10 or Windows 11 (64-bit recommended)
- **Python:** Python 3.10+
- **Privileges:** Administrator privileges (required for ETW kernel network event capture and Windows Firewall modification). If started unprivileged, NetWatch prompts to elevate via UAC.

### Python Dependencies

- `PyQt6 >= 6.5`
- `psutil >= 5.9`
- `pywintrace >= 0.2.0` (Windows kernel ETW consumer)

---

## 🚀 Installation & Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/MCnima/NetWatch.git
cd NetWatch
```

### 2. Choose an Edition & Install Dependencies

Navigate into either `NetWatch` or `NetWatch2`:

```bash
# For NetWatch 2 (recommended)
cd NetWatch2

# Create and activate a virtual environment (optional but recommended)
python -m venv venv
venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### 3. Run the Application

Launch the application with administrator privileges:

```bash
python main.py
```

> **Note:** If launched without Administrator rights, basic adapter stats will still function, but per-app ETW tracking and firewall management will prompt for elevation.

---

## 🔨 Building Standalone Executables & Installers

Both versions include a `build.bat` script and Inno Setup configuration (`installer.iss`) to package the program into a single executable and setup wizard.

### Requirements for Building:
- `pyinstaller`
- [Inno Setup 6.3+](https://jrsoftware.org/isdl.php) (optional, ensure `ISCC.exe` is added to your system `PATH`)

### Run the Build Script:

```cmd
cd NetWatch2
build.bat
```

- **Executable:** Output located at `dist\NetWatch\NetWatch.exe`
- **Setup Installer:** If Inno Setup is detected, generated at `installer\NetWatch-Setup.exe`

---

## 🛡️ Firewall Management (NetWatch 2)

NetWatch 2 manages application network access via native `netsh advfirewall firewall` rules:
- **LAN-Friendly Mode:** Isolates traffic by targeting public IPv4 (`PUBLIC_V4`) and IPv6 (`2000::/3`) IP ranges, allowing you to block an app from the wider web while retaining access to local media servers, printers, or local databases.
- **Safety Safeguards:** System-critical executables (`svchost.exe`, `lsass.exe`, `services.exe`, etc.) are protected from accidental blocking.
- **State Synchronization:** NetWatch stores an index in `%PROGRAMDATA%\NetWatch\blocks.json` and synchronizes with active Windows Firewall rules at startup.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

```text
MIT License

Copyright (c) 2026 MCnima

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```