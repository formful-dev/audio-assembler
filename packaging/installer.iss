; Inno Setup script: builds dist\AudioAssembler-<version>-Setup.exe from dist\Audio Assembler\
; Build with packaging\build_windows.ps1 (or: ISCC.exe /DAppVersion=0.1.0 packaging\installer.iss)

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Audio Assembler"
#define AppExe "Audio Assembler.exe"

[Setup]
AppId={{BD536B78-07F0-44D1-BED1-6ADB8ADAD505}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without asking for administrator rights;
; the user can choose "install for all users" instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=AudioAssembler-{#AppVersion}-Setup
SetupIconFile=..\src\audio_assembler\gui\resources\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Audio Assembler\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}\licenses"; DestName: "Audio-Assembler-MIT.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent
