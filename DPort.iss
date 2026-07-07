; ─────────────────────────────────────────────────────────────────────────
;  DPort — Inno Setup kurulum betigi
;  Derleme: once Build.bat (PyInstaller -> dist\DPort\DPort.exe),
;           sonra bu dosyayi Inno Setup ile derle (ISCC DPort.iss).
;  Cikti:   installer\DPort-Setup-<surum>.exe
; ─────────────────────────────────────────────────────────────────────────

#define MyAppName "DPort"
#define MyAppVersion "2.5"
#define MyAppPublisher "IzzmooPro"
#define MyAppExeName "DPort.exe"
#define MyAppId "{{7C9E6A54-2D3B-4F81-A6E2-1B0C9D8E7F60}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=DPort Kurulum

; Program Files\DPort (yonetici gerekir)
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

; Kurulum yonetici ister (DPort zaten yonetici haklariyla calisir)
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

; Kurulum sirasinda calisan DPort'u kapatmaya calis (guncelleme icin)
CloseApplications=yes
RestartApplications=no

; Cikti
OutputDir=installer
OutputBaseFilename=DPort-Setup-{#MyAppVersion}
SetupIconFile=app\assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Kurulum bitince istege bagli baslat
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runascurrentuser

[UninstallRun]
; 1) Calisan DPort'u kapat
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillApp"
; 2) hosts yonlendirmesini temizle (sistemi eski haline getir)
Filename: "{app}\{#MyAppExeName}"; Parameters: "--cleanup-hosts"; Flags: runhidden waituntilterminated; RunOnceId: "CleanupHosts"
; 3) logon guvenlik gorevini sil
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""DPortHostsFailsafe"" /F"; Flags: runhidden; RunOnceId: "DelTask"

; Not: Kullanici ayarlari/loglari (%APPDATA%\DPort) kaldirmada SILINMEZ; kullanici
; tekrar kurarsa ayarlari korunur. Onemli sistem degisiklikleri (hosts + gorev)
; yukaridaki adimlarla geri alinir.

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
