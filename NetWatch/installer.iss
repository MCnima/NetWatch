; Inno Setup 6.3+ script. Run via build.bat, or open in the Inno Setup compiler.
[Setup]
AppName=NetWatch
AppVersion=1.0.0
DefaultDirName={autopf}\NetWatch
DefaultGroupName=NetWatch
OutputDir=installer
OutputBaseFilename=NetWatch-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallMode=x64compatible
UninstallDisplayIcon={app}\NetWatch.exe

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\NetWatch\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\NetWatch"; Filename: "{app}\NetWatch.exe"
Name: "{autodesktop}\NetWatch"; Filename: "{app}\NetWatch.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NetWatch.exe"; Description: "Launch NetWatch"; Flags: nowait postinstall skipifsilent shellexec
