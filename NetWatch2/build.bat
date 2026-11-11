@echo off
REM Builds NetWatch.exe (PyInstaller) and, if Inno Setup is installed, NetWatch-Setup.exe
setlocal
python -m pip install -r requirements.txt pyinstaller || exit /b 1
pyinstaller --noconfirm --windowed --uac-admin --name NetWatch --collect-submodules etw main.py || exit /b 1
where iscc >nul 2>nul
if errorlevel 1 (
  echo.
  echo Built dist\NetWatch\NetWatch.exe
  echo Install Inno Setup 6.3+ and put ISCC.exe on PATH to also produce the installer.
) else (
  iscc installer.iss || exit /b 1
  echo.
  echo Installer created: installer\NetWatch-Setup.exe
)
