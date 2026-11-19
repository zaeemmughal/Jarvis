; Inno Setup script for J.A.R.V.I.S  -  compile AFTER running build_exe.bat
#define AppName "J.A.R.V.I.S"
#define AppVersion "1.0.0"
#define AppExe "Jarvis.exe"

[Setup]
AppId={{B7E4C2A1-5D3F-4A8E-9C61-2F0A7D9E1B34}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Zaeem
DefaultDirName={autopf}\Jarvis
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=Jarvis_Setup
SetupIconFile=jarvis.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start Jarvis in the background when I log in to Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\Jarvis\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Put a copy of your working .env at installer\default.env to ship your keys inside the installer (see notes)
#ifexist "default.env"
Source: "default.env"; DestDir: "{app}"; DestName: ".env"; Flags: ignoreversion
#endif

[Icons]
Name: "{group}\J.A.R.V.I.S"; Filename: "{app}\{#AppExe}"
Name: "{group}\J.A.R.V.I.S (background)"; Filename: "{app}\{#AppExe}"; Parameters: "--background"
Name: "{group}\Edit settings (.env)"; Filename: "notepad.exe"; Parameters: """{userappdata}\Jarvis\.env"""
Name: "{group}\Uninstall J.A.R.V.I.S"; Filename: "{uninstallexe}"
Name: "{autodesktop}\J.A.R.V.I.S"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Jarvis"; ValueData: """{app}\{#AppExe}"" --background"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch J.A.R.V.I.S now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
