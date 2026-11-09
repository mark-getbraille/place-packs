; Inno Setup script for Photo Location Identifier. Built by .github/workflows/photo-location-identifier.yml:
;   ISCC.exe /DAppVersion=1.0.0 installer\pli.iss      (from the photo-location-identifier folder)
; Installs for the current user by default (no administrator question; the installer offers all users too), adds
; "Sort pictures by location" to File Explorer's menu for folders and for the inside of a folder, a Start menu
; entry, the manual, and a desktop shortcut. Inno Setup's standard windows are read by NVDA, JAWS and Narrator,
; including the progress bar.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Photo Location Identifier"
#define AppExe "PhotoLocationIdentifier.exe"
#define Publisher "Company Maker, LLC"

[Setup]
AppId={{6C1E3A52-8E0B-4F7B-9B8E-3D0E5C2A7F41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL=https://github.com/mark-getbraille/place-packs
AppSupportURL=https://github.com/mark-getbraille/place-packs/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir=..\dist
OutputBaseFilename=PhotoLocationIdentifier-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\PhotoLocationIdentifier\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} manual"; Filename: "{app}\_internal\docs\manual.html"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; File Explorer: right-click a folder.
Root: HKA; Subkey: "Software\Classes\Directory\shell\PhotoLocationIdentifier"; ValueType: string; ValueName: ""; ValueData: "Sort pictures by location"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\PhotoLocationIdentifier"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKA; Subkey: "Software\Classes\Directory\shell\PhotoLocationIdentifier\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --open ""%1"""
; File Explorer: right-click inside an open folder (its background).
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\PhotoLocationIdentifier"; ValueType: string; ValueName: ""; ValueData: "Sort pictures by location"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\PhotoLocationIdentifier"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\PhotoLocationIdentifier\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --open ""%V"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent
