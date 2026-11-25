#define AppName "桌宠便签"
#define Publisher "Ygxai"
#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif
#ifndef OutputTag
  #define OutputTag AppVersion
#endif
#ifndef DistRoot
  #define DistRoot "dist\DeskPetNotes"
#endif

[Setup]
AppId={{A29D5EF1-A68B-4926-BBAB-26E4102595E5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppCopyright=Copyright © 2026 {#Publisher}
LicenseFile={#DistRoot}\licenses\DeskPetNotes-LICENSE.txt
DefaultDirName={localappdata}\Programs\DeskPetNotes
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
DisableProgramGroupPage=yes
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=..\..\outputs
OutputBaseFilename=DeskPetNotes-Setup-{#OutputTag}
UninstallDisplayIcon={app}\DeskPetNotes.exe
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "{#DistRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icudt78.dll"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\DeskPetNotes.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\DeskPetNotes.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Run]
Filename: "{app}\DeskPetNotes.exe"; Description: "打开桌宠便签"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{userstartup}\DeskPetNotes.bat"
