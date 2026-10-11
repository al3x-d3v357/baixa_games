; Instalador Catalogo PSP — Inno Setup 6
; Uso: Criar-Instalador.bat (gera dist\CatalogoPSP.exe e depois Setup)
#define MyAppName "Catalogo PSP"
#define MyAppVersion "2.1"
#define MyAppPublisher "baixa_games"
#define MyAppExeName "CatalogoPSP.exe"

[Setup]
AppId={{8F2E4B1A-3C7D-4E9A-PSP2-ANIMADO}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\CatalogoPSP
DefaultGroupName=Catalogo PSP
OutputDir=..\dist
OutputBaseFilename=CatalogoPSP-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=no
UninstallDisplayName={#MyAppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Dirs]
Name: "{app}\downloads"; Flags: uninsneveruninstall
Name: "{app}\capas"; Flags: uninsneveruninstall

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\catalogo-psp.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\lista.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Catalogo PSP"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Catalogo PSP"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o Catalogo PSP agora"; Flags: nowait postinstall skipifsilent
