#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

[Setup]
AppId={{E286B5DF-DA3D-4EA0-87BA-5E81DD6F478B}
AppName=ScreenTranslator
AppVersion=0.2.0
AppPublisher=OsKamio
AppPublisherURL=https://github.com/OsKamio/screen-translator
DefaultDirName={localappdata}\Programs\ScreenTranslator
DefaultGroupName=ScreenTranslator
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=ScreenTranslator-0.2.0-Setup-x64
SetupIconFile=..\assets\screen-translator.ico
UninstallDisplayIcon={app}\ScreenTranslator.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "chinesetraditional"; MessagesFile: "languages\ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ScreenTranslator"; Filename: "{app}\ScreenTranslator.exe"; AppUserModelID: "ScreenTranslator.Desktop.1"
Name: "{autodesktop}\ScreenTranslator"; Filename: "{app}\ScreenTranslator.exe"; Tasks: desktopicon; AppUserModelID: "ScreenTranslator.Desktop.1"

[Run]
Filename: "{app}\ScreenTranslator.exe"; Description: "{cm:LaunchProgram,ScreenTranslator}"; Flags: nowait postinstall skipifsilent

; User preferences and API credentials live in APPDATA and are deliberately
; absent from [Files] and [UninstallDelete]. Upgrades/uninstall retain them.
