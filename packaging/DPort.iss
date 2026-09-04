; ─────────────────────────────────────────────────────────────────────────
;  DPort — Inno Setup kurulum betigi
;  Derleme: once scripts\Build.bat (PyInstaller -> dist\DPort\DPort.exe),
;           sonra bu dosyayi Inno Setup ile derle (ISCC packaging\DPort.iss).
;  Cikti:   installer\DPort-Setup-<surum>.exe
; ─────────────────────────────────────────────────────────────────────────

#define MyAppName "DPort"
#define MyAppVersion "3.13"
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

; KURULUM DIZINI POLITIKASI (guvenlik)
; ONLOGON + HIGHEST failsafe gorevinin hedefi, kullanici tarafindan
; DEGISTIRILEMEYEN bir konumda olmak ZORUNDADIR. Bu yuzden:
;   - DisableDirPage=yes : kullanici sihirbazda baska bir dizin secemez.
;   - UsePreviousAppDir=no: onceki (belki custom, belki gevsek ACL'li) kurulum
;     dizini SESSIZCE devralinmaz; her zaman {autopf}\DPort kullanilir.
; `/DIR=` komut satiri hala geciriebilir; bu yuzden hedef, gorev kurulmadan
; once [Code] icinde BAGIMSIZ olarak dogrulanir (PathIsVerifiedInstall) ve
; dogrulanamazsa kurulum gorunur bicimde basarisiz olur.
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=yes
UsePreviousAppDir=no
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
OutputDir=..\installer
OutputBaseFilename=DPort-Setup-{#MyAppVersion}
SetupIconFile=..\app\assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Bayrak yok = kutu VARSAYILAN OLARAK ISARETLI gelir (masaustu kisayolu olusur).
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ikonu ayrica kurulum kokune acikca kopyala (assets alt klasorunden bagimsiz,
; kararli bir yol); kisayollar bu dosyayi acikca referans alir.
Source: "..\app\assets\icon.ico"; DestDir: "{app}"; DestName: "icon.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; IconIndex: 0
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"; IconIndex: 0

[Run]
; Kurulum bitince istege bagli baslat. DPort.exe yonetici (requireAdministrator)
; ister; runascurrentuser ile CreateProcess "kod 740" verir. shellexec, ShellExecute
; kullanip manifesti onurlandirir ve dogru sekilde yukseltir.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent shellexec

; Not: Kaldirma temizligi (hosts blogunu sil + failsafe gorevini sil + calisan
; DPort'u kapat) [Code] icinde CurUninstallStepChanged'te yapilir. Eski [UninstallRun]
; yaklasimi ({sys} + admin-exe --cleanup-hosts) kaldiricida "PathRedir: Not
; initialized" ic hatasi veriyordu. Kullanici ayarlari (%APPDATA%\DPort) SILINMEZ.

[Code]
const
  SHCNE_ASSOCCHANGED = $08000000;
  SHCNF_IDLIST       = $0000;
  { TASK_NAME / LEGACY_TASK, testlerin ayikladigi karar blogunun icinde
    tanimlidir (bkz. DPORT FAILSAFE TASK BEGIN): blok kendi kendine yeterli
    olmalidir. }

procedure SHChangeNotify(wEventId: LongWord; uFlags: LongWord; dwItem1: LongWord; dwItem2: LongWord);
  external 'SHChangeNotify@shell32.dll stdcall';

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

{ DIKKAT: Asagidaki isaretli blok tests/test_failsafe_reconcile.py tarafindan
  AYIKLANIP ayri bir deneme kurulumuna derlenir ve GECICI fixture dosyalari
  uzerinde CALISTIRILIR. Blok kendi kendine yeterli olmalidir (disaridaki
  sabitlere/rutinlere bagli degil) ve isaret satirlari AYNEN korunmalidir. }
{ ===== DPORT HOSTS CLEANER BEGIN ===== }
const
  HOSTS_BEGIN  = '# >>> DPort Discord unblock >>>';
  HOSTS_END    = '# <<< DPort Discord unblock <<<';
  LEGACY_BEGIN = '# >>> DNSGuardian Discord unblock >>>';
  LEGACY_END   = '# <<< DNSGuardian Discord unblock <<<';

function SetFileAttributesW(lpFileName: string; dwAttrs: LongWord): Boolean;
  external 'SetFileAttributesW@kernel32.dll stdcall';

{ Satir, DPort'un YAZDIGI yonlendirmelerden biri mi? Yalniz tam olarak
  '127.0.0.1 <bilinen discord host>' bicimindeki satirlar bize aittir;
  app/core/discord_unblock.py::BLOCKED_HOSTS ile ayni kume. }
function HostsLineIsOurRedirect(const Line: string): Boolean;
var
  S, Host: string;
begin
  Result := False;
  S := Trim(Line);
  if Copy(S, 1, 9) <> '127.0.0.1' then exit;
  { 10. karakter bir ayirici olmali: '127.0.0.10 x' veya '127.0.0.1x' bize ait
    degildir. Trim sonrasi tek bir alan kalmalidir. }
  S := Trim(Copy(S, 10, Length(S)));
  if S = '' then exit;
  if Pos(' ', S) > 0 then exit;
  if Pos(#9, S) > 0 then exit;
  Host := Lowercase(S);
  Result := (Host = 'updates.discord.com') or (Host = 'discord.com')
         or (Host = 'gateway.discord.gg') or (Host = 'cdn.discordapp.com')
         or (Host = 'media.discordapp.net');
end;

{ Metinde DPort/legacy isaretcisi ya da bize ait bir yonlendirme kalmis mi? }
function HostsHasDPortResidue(const Lines: TArrayOfString): Boolean;
var
  I: Integer;
  S: string;
begin
  Result := True;
  for I := 0 to GetArrayLength(Lines) - 1 do begin
    S := Trim(Lines[I]);
    if (S = HOSTS_BEGIN) or (S = HOSTS_END)
       or (S = LEGACY_BEGIN) or (S = LEGACY_END) then exit;
    if HostsLineIsOurRedirect(S) then exit;
  end;
  Result := False;
end;

function CleanHostsBlockUnsafe(const HostsPath: string): Boolean;
var
  Lines, OutLines, Verify: TArrayOfString;
  I, N: Integer;
  S: string;
  Skip: Boolean;
begin
  Result := False;

  { Dosya yok -> temizlenecek yonlendirme de yok: DOGRULANMIS temiz durum. }
  if not FileExists(HostsPath) then begin
    Result := True;
    exit;
  end;
  if not LoadStringsFromFile(HostsPath, Lines) then begin
    Log('DPort: hosts OKUNAMADI: ' + HostsPath);
    exit;
  end;
  { Isaretli blok ya da yonlendirme yok -> yazma YAPMA (kullanici dosyasini
    gereksiz yere yeniden yazmayiz), ama durum dogrulanmis temizdir. }
  if not HostsHasDPortResidue(Lines) then begin
    Result := True;
    exit;
  end;

  SetArrayLength(OutLines, GetArrayLength(Lines));
  N := 0;
  Skip := False;
  for I := 0 to GetArrayLength(Lines) - 1 do begin
    S := Trim(Lines[I]);
    if (S = HOSTS_BEGIN) or (S = LEGACY_BEGIN) then begin Skip := True; continue; end;
    if (S = HOSTS_END) or (S = LEGACY_END) then begin Skip := False; continue; end;
    if Skip then begin
      { VERI KAYBI KORUMASI: bitis isareti eksikse (yarim yazma, elle mudahale)
        dosyanin GERI KALANI silinmemeli. Skip modunda YALNIZCA kendi bildigimiz
        yonlendirme satirlarini sileriz; yabanci bir satir gelince blogu bitmis
        sayar ve o satiri KORURUZ. (Ayni ilke:
        app/core/discord_unblock.py::_strip_block) }
      if HostsLineIsOurRedirect(S) then continue;
      Skip := False;
    end;
    OutLines[N] := Lines[I];
    N := N + 1;
  end;
  SetArrayLength(OutLines, N);

  if not SetFileAttributesW(HostsPath, FILE_ATTRIBUTE_NORMAL) then begin
    Log('DPort: hosts dosya nitelikleri degistirilemedi: ' + HostsPath);
    exit;
  end;
  if not SaveStringsToFile(HostsPath, OutLines, False) then begin
    Log('DPort: hosts YAZILAMADI: ' + HostsPath);
    exit;
  end;

  { Sonucu DISKTEN yeniden okuyup dogrula: isaretci veya yonlendirme kalmissa
    temizlik BASARISIZ sayilir (gorev bu yuzden korunur). }
  if not LoadStringsFromFile(HostsPath, Verify) then begin
    Log('DPort: hosts yazildi ama GERI OKUNAMADI: ' + HostsPath);
    exit;
  end;
  if HostsHasDPortResidue(Verify) then begin
    Log('DPort: hosts temizligi DOGRULANAMADI (kalinti var): ' + HostsPath);
    exit;
  end;
  Result := True;
end;

{ hosts dosyasindan yalnizca DPort/DNSGuardian isaretli blogunu siler; reklam
  engelleyici gibi diger tum satirlar korunur. Salt-okunur ise once acar.
  Donus: temizlik DISKTEN DOGRULANDI mi. False ise cagiran failsafe gorevini
  SILMEMELIDIR. }
function CleanHostsBlock(const HostsPath: string): Boolean;
begin
  try
    Result := CleanHostsBlockUnsafe(HostsPath);
  except
    Log('DPort: hosts temizliginde beklenmeyen hata: ' + GetExceptionMessage);
    Result := False;
  end;
end;
{ ===== DPORT HOSTS CLEANER END ===== }

function HostsFilePath(): string;
begin
  Result := ExpandConstant('{win}\System32\drivers\etc\hosts');
end;

{ ── Hedef dogrulama ILKELLERI ─────────────────────────────────────────────
  Asagidaki isaretli KARAR blogu yalnizca bu dort rutini kullanir. Testler ayni
  karar blogunu ayiklayip SAHTE ilkellerle derleyip calistirir. }

function GetFullPathNameW(lpFileName: string; nBufferLength: LongWord;
  lpBuffer: string; lpFilePart: LongWord): LongWord;
  external 'GetFullPathNameW@kernel32.dll stdcall';

function GetLongPathNameW(lpszShortPath: string; lpszLongPath: string;
  cchBuffer: LongWord): LongWord;
  external 'GetLongPathNameW@kernel32.dll stdcall';

function GetFileAttributesW(lpFileName: string): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

{ Yolu GERCEK, tam nitelikli ve UZUN adli haline cevirir.
  - Goreli yol / '..' cozulur (GetFullPathName)
  - 8.3 kisa ad acilir (GetLongPathName); bu ayni zamanda yolun GERCEKTEN
    VAR OLDUGUNU da dogrular (yoksa cagri basarisiz olur)
  - Ag (UNC) yolu korumali kurulum sayilmaz -> reddedilir
  Junction/symlink burada COZULMEZ; zincir ayrica reparse point yonunden
  denetlenir ve varsa yol tamamen REDDEDILIR. }
function PathCanonical(const Path: string; var Canon: string): Boolean;
var
  Buf: string;
  Len: LongWord;
begin
  Result := False;
  Canon := '';
  if Trim(Path) = '' then exit;
  if Copy(Path, 1, 2) = '\\' then exit;
  SetLength(Buf, 4096);
  Len := GetFullPathNameW(Path, 4096, Buf, 0);
  if (Len = 0) or (Len >= 4096) then exit;
  SetLength(Buf, Integer(Len));
  Canon := Buf;
  SetLength(Buf, 4096);
  Len := GetLongPathNameW(Canon, Buf, 4096);
  if (Len = 0) or (Len >= 4096) then exit;
  SetLength(Buf, Integer(Len));
  Canon := Buf;
  if Copy(Canon, 1, 2) = '\\' then begin Canon := ''; exit; end;
  Result := True;
end;

{ Donus False = durum OKUNAMADI (cagiran FAIL CLOSED davranir). }
function PathIsReparse(const Path: string; var IsReparse: Boolean): Boolean;
var
  Attrs: LongWord;
begin
  IsReparse := False;
  Attrs := GetFileAttributesW(Path);
  if Attrs = $FFFFFFFF then begin
    Result := False;
    exit;
  end;
  IsReparse := (Attrs and $00000400) <> 0;   { FILE_ATTRIBUTE_REPARSE_POINT }
  Result := True;
end;

procedure AddRoot(var Roots: TArrayOfString; const Value: string);
var
  I, N: Integer;
  Clean: string;
begin
  Clean := Trim(Value);
  if Clean = '' then exit;
  while (Length(Clean) > 3) and (Clean[Length(Clean)] = '\') do
    Clean := Copy(Clean, 1, Length(Clean) - 1);
  for I := 0 to GetArrayLength(Roots) - 1 do
    if CompareText(Roots[I], Clean) = 0 then exit;
  N := GetArrayLength(Roots);
  SetArrayLength(Roots, N + 1);
  Roots[N] := Clean;
end;

{ GERCEK Program Files kokleri. ORTAM DEGISKENI KULLANILMAZ: kullanici
  HKCU\Environment uzerinden ProgramFiles/ProgramW6432 degerlerini
  degistirebildigi icin bunlar guvenilmez. Iki bagimsiz, YALNIZ YONETICININ
  yazabildigi kaynak kullanilir:
    1. Inno'nun kabuk API'sinden turettigi commonpf32 / commonpf64 sabitleri
    2. HKLM\...\CurrentVersion altindaki ProgramFilesDir degerleri }
function ProgramFilesRoots(var Roots: TArrayOfString): Boolean;
var
  S: string;
begin
  SetArrayLength(Roots, 0);
  try
    AddRoot(Roots, ExpandConstant('{commonpf32}'));
  except
  end;
  try
    AddRoot(Roots, ExpandConstant('{commonpf64}'));
  except
  end;
  if RegQueryStringValue(HKEY_LOCAL_MACHINE,
       'SOFTWARE\Microsoft\Windows\CurrentVersion', 'ProgramFilesDir', S) then
    AddRoot(Roots, S);
  if RegQueryStringValue(HKEY_LOCAL_MACHINE,
       'SOFTWARE\Microsoft\Windows\CurrentVersion', 'ProgramFilesDir (x86)', S) then
    AddRoot(Roots, S);
  if RegQueryStringValue(HKEY_LOCAL_MACHINE,
       'SOFTWARE\Microsoft\Windows\CurrentVersion', 'ProgramW6432Dir', S) then
    AddRoot(Roots, S);
  Result := GetArrayLength(Roots) > 0;
end;

function CapturedLinesText(const Lines: TArrayOfString): string;
var
  I: Integer;
begin
  Result := '';
  for I := 0 to GetArrayLength(Lines) - 1 do begin
    if Result <> '' then Result := Result + #13#10;
    Result := Result + Lines[I];
  end;
end;

{ Nesnenin guvenlik tanimlayicisini SDDL metni olarak dondurur (sahip + DACL).
  DACL'i isaretci aritmetigiyle gezmek yerine metin olarak almak, Pascal Script
  icinde deterministik ve denetlenebilir bir cozumleme saglar.
  powershell.exe MUTLAK yoldan (System32) calistirilir; PATH'e guvenilmez.

  GUVENLIK: Sonuc kullanici-yazilabilir TEMP dosyasina konmaz. Ayricalikli
  installer, stdout'u dogrudan Inno'nun pipe'i uzerinden yakalar; araya baska
  bir surecin degistirebilecegi karar dosyasi girmez. }
function PathSddl(const Path: string; var Sddl: string): Boolean;
var
  QuotedPath, Params: string;
  Code: Integer;
  Output: TExecOutput;
begin
  Result := False;
  Sddl := '';
  QuotedPath := Path;
  StringChangeEx(QuotedPath, '''', '''''', True);
  Params := '-NoProfile -NonInteractive -Command "$ErrorActionPreference='
          + '''Stop''; $a = Get-Acl -LiteralPath ''' + QuotedPath + ''';'
          + ' [Console]::Out.Write($a.Sddl)"';
  try
    if not ExecAndCaptureOutput(
      ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Params, '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code, Output) then exit;
  except
    Log('DPort: ACL ciktisi yakalanamadi: ' + GetExceptionMessage);
    exit;
  end;
  if (Code <> 0) or Output.Error then exit;
  if Trim(CapturedLinesText(Output.StdErr)) <> '' then exit;
  Sddl := Trim(CapturedLinesText(Output.StdOut));
  Result := Sddl <> '';
end;

{ ===== DPORT SAFE TARGET BEGIN ===== }
{ HIGHEST yetkili gorevin hedefi olabilecek yolun BAGIMSIZ dogrulamasi.

  `FileExists` bir guvenlik kontrolu DEGILDIR: custom /DIR=, onceki kurulumdan
  devralinan dizin, gevsek ACL veya junction uzerinden kullanici-yazilabilir bir
  DPort.exe de "var"dir. Standart kullanici o dosyayi kendi yuku ile
  degistirirse her oturum acilista UAC'siz, KALICI yetki yukseltmesi elde eder.

  Bu blok app/core/failsafe.py::path_is_verified_install ile AYNI olcutleri
  uygular: canonical yol, gercek Program Files koku, zincirde reparse point yok,
  dosya VE ust dizinde yalnizca ayricalikli principal'lar yazma/silme/ACL hakki
  tutuyor, sahip ayricalikli. Herhangi bir okuma hatasinda FAIL CLOSED. }
const
  { Dosyayi DEGISTIRMEYE veya izinlerini ele gecirmeye yarayan haklar:
    WRITE_DATA|APPEND|WRITE_EA|DELETE_CHILD|WRITE_ATTRIBUTES
    |DELETE|WRITE_DAC|WRITE_OWNER|GENERIC_ALL|GENERIC_WRITE }
  DANGEROUS_RIGHTS = $500D0156;

function SidIsTrustedWriter(const Sid: string): Boolean;
begin
  Result := (Sid = 'SY') or (Sid = 'S-1-5-18')            { SYSTEM }
         or (Sid = 'BA') or (Sid = 'S-1-5-32-544')        { Administrators }
         or (Sid = 'CO') or (Sid = 'S-1-3-0')             { CREATOR OWNER }
         or (Sid = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464');
end;

function SidIsTrustedOwner(const Sid: string): Boolean;
begin
  { Sahip DACL'i her zaman degistirebilir; CREATOR OWNER bir sahip degeri
    DEGILDIR ve burada kabul EDILMEZ. }
  Result := (Sid = 'SY') or (Sid = 'S-1-5-18')
         or (Sid = 'BA') or (Sid = 'S-1-5-32-544')
         or (Sid = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464');
end;

function HexToCardinal(const S: string; var Value: Cardinal): Boolean;
var
  I, D: Integer;
  C: string;
begin
  Result := False;
  Value := 0;
  if (Length(S) = 0) or (Length(S) > 8) then exit;
  for I := 1 to Length(S) do begin
    C := Uppercase(Copy(S, I, 1));
    if (C >= '0') and (C <= '9') then D := Ord(C[1]) - Ord('0')
    else if (C >= 'A') and (C <= 'F') then D := Ord(C[1]) - Ord('A') + 10
    else exit;
    Value := (Value * 16) + Cardinal(D);
  end;
  Result := True;
end;

{ SDDL hak kisaltmasi -> erisim maskesi. TANIMADIGIMIZ hicbir kisaltma
  yok sayilmaz; cozumleme basarisiz olur ve cagiran FAIL CLOSED davranir. }
function RightsPairMask(const Pair: string; var Mask: Cardinal): Boolean;
begin
  Result := True;
  if      Pair = 'GA' then Mask := $10000000
  else if Pair = 'GX' then Mask := $20000000
  else if Pair = 'GW' then Mask := $40000000
  else if Pair = 'GR' then Mask := $80000000
  else if Pair = 'SD' then Mask := $00010000
  else if Pair = 'RC' then Mask := $00020000
  else if Pair = 'WD' then Mask := $00040000
  else if Pair = 'WO' then Mask := $00080000
  else if Pair = 'FA' then Mask := $001F01FF
  else if Pair = 'FR' then Mask := $00120089
  else if Pair = 'FW' then Mask := $00120116
  else if Pair = 'FX' then Mask := $001200A0
  else if Pair = 'CC' then Mask := $00000001
  else if Pair = 'DC' then Mask := $00000002
  else if Pair = 'LC' then Mask := $00000004
  else if Pair = 'SW' then Mask := $00000008
  else if Pair = 'RP' then Mask := $00000010
  else if Pair = 'WP' then Mask := $00000020
  else if Pair = 'DT' then Mask := $00000040
  else if Pair = 'LO' then Mask := $00000080
  else if Pair = 'CR' then Mask := $00000100
  else begin
    Mask := 0;
    Result := False;
  end;
end;

function SddlRightsMask(const Token: string; var Mask: Cardinal): Boolean;
var
  I: Integer;
  Bit: Cardinal;
begin
  Result := False;
  Mask := 0;
  if Token = '' then exit;
  if Copy(Token, 1, 2) = '0X' then begin
    Result := HexToCardinal(Copy(Token, 3, Length(Token)), Mask);
    exit;
  end;
  if (Length(Token) mod 2) <> 0 then exit;
  I := 1;
  while I < Length(Token) do begin
    if not RightsPairMask(Copy(Token, I, 2), Bit) then exit;
    Mask := Mask or Bit;
    I := I + 2;
  end;
  Result := True;
end;

{ ACE bayraklari IKI KARAKTERLIK belirteclerden olusur. Duz alt-dizgi aramasi
  ('OI'+'OI' -> "OIOI") yanlislikla 'IO' bulur; bu yuzden cift cift gezilir. }
function AceHasFlag(const Flags, Flag: string): Boolean;
var
  I: Integer;
begin
  Result := False;
  if (Length(Flags) mod 2) <> 0 then exit;
  I := 1;
  while I < Length(Flags) do begin
    if Copy(Flags, I, 2) = Flag then begin
      Result := True;
      exit;
    end;
    I := I + 2;
  end;
end;

function SplitAce(const Ace: string; var Fields: TArrayOfString): Boolean;
var
  I, N, Start: Integer;
begin
  SetArrayLength(Fields, 6);
  N := 0;
  Start := 1;
  for I := 1 to Length(Ace) do begin
    if Ace[I] = ';' then begin
      if N >= 6 then begin Result := False; exit; end;
      Fields[N] := Copy(Ace, Start, I - Start);
      N := N + 1;
      Start := I + 1;
    end;
  end;
  if N <> 5 then begin Result := False; exit; end;
  Fields[5] := Copy(Ace, Start, Length(Ace) - Start + 1);
  Result := True;
end;

{ Donus False = ACE cozumlenemedi (FAIL CLOSED).
  Ok=False = bu ACE dusuk yetkili bir principal'a tehlikeli hak veriyor. }
function AceIsHarmless(const Ace: string; var Ok: Boolean): Boolean;
var
  Fields: TArrayOfString;
  Mask: Cardinal;
  AceType, Flags: string;
begin
  Result := False;
  Ok := True;
  if not SplitAce(Ace, Fields) then exit;
  AceType := Uppercase(Trim(Fields[0]));
  Flags := Uppercase(Trim(Fields[1]));
  { DENY ACE'leri bilincli olarak YOK SAYILIR: bir deny yalnizca izni
    DARALTABILIRDI, hesaba katmamak bizi daha KATI yapar. }
  if AceType = 'D' then begin Result := True; exit; end;
  if AceType <> 'A' then exit;             { taninmayan ACE turu -> fail closed }
  { INHERIT_ONLY: bu nesneye uygulanmaz. }
  if AceHasFlag(Flags, 'IO') then begin Result := True; exit; end;
  if not SddlRightsMask(Uppercase(Trim(Fields[2])), Mask) then exit;
  if (Mask and DANGEROUS_RIGHTS) = 0 then begin Result := True; exit; end;
  Ok := SidIsTrustedWriter(Uppercase(Trim(Fields[5])));
  Result := True;
end;

{ Donus False = DACL cozumlenemedi. Ok=False = guvensiz. }
function AclWritersAreTrusted(const Dacl: string; var Ok: Boolean): Boolean;
var
  I, Depth, Start: Integer;
begin
  Result := False;
  Ok := True;
  Depth := 0;
  Start := 0;
  for I := 1 to Length(Dacl) do begin
    if Dacl[I] = '(' then begin
      if Depth <> 0 then exit;
      Depth := 1;
      Start := I + 1;
    end else if Dacl[I] = ')' then begin
      if Depth <> 1 then exit;
      Depth := 0;
      if not AceIsHarmless(Copy(Dacl, Start, I - Start), Ok) then exit;
      if not Ok then begin Result := True; exit; end;
    end;
  end;
  if Depth <> 0 then exit;
  Result := True;
end;

{ 'O:' / 'D:' bolumunu ayiklar. Bolum sonu, PARANTEZ DISINDA gecen bir
  sonraki 'O:'/'G:'/'D:'/'S:' basligidir. }
function SddlSection(const Sddl, Tag: string; var Value: string): Boolean;
var
  I, P, Q, Depth: Integer;
  Rest, C: string;
begin
  Result := False;
  Value := '';
  P := Pos(Tag, Sddl);
  if P = 0 then exit;
  Rest := Copy(Sddl, P + 2, Length(Sddl) - P - 1);
  Depth := 0;
  Q := 0;
  for I := 1 to Length(Rest) do begin
    C := Copy(Rest, I, 1);
    if C = '(' then Depth := Depth + 1
    else if C = ')' then Depth := Depth - 1
    else if (Depth = 0) and (I < Length(Rest)) and (Copy(Rest, I + 1, 1) = ':')
            and ((C = 'O') or (C = 'G') or (C = 'D') or (C = 'S')) then begin
      Q := I;
      break;
    end;
  end;
  if Q > 0 then Value := Copy(Rest, 1, Q - 1) else Value := Rest;
  Value := Trim(Value);
  Result := True;
end;

function LocationIsAclProtected(const Path: string; var Reason: string): Boolean;
var
  Sddl, Owner, Dacl: string;
  Ok: Boolean;
begin
  Result := False;
  if not PathSddl(Path, Sddl) then begin
    Reason := 'guvenlik tanimlayicisi okunamadi: ' + Path;
    exit;
  end;
  if not SddlSection(Sddl, 'O:', Owner) then begin
    Reason := 'SDDL sahibi cozulemedi: ' + Path;
    exit;
  end;
  if not SidIsTrustedOwner(Uppercase(Trim(Owner))) then begin
    Reason := 'nesne sahibi ayricalikli degil (' + Owner + '): ' + Path;
    exit;
  end;
  if not SddlSection(Sddl, 'D:', Dacl) then begin
    Reason := 'SDDL DACL cozulemedi: ' + Path;
    exit;
  end;
  if not AclWritersAreTrusted(Dacl, Ok) then begin
    Reason := 'DACL cozumlenemedi (fail closed): ' + Path;
    exit;
  end;
  if not Ok then begin
    Reason := 'dusuk yetkili principal yazma/silme/ACL hakki tutuyor: ' + Path;
    exit;
  end;
  Result := True;
end;

function PathIsUnderRoot(const Canon: string;
                         const Roots: TArrayOfString): Boolean;
var
  I: Integer;
  Root: string;
begin
  Result := False;
  for I := 0 to GetArrayLength(Roots) - 1 do begin
    Root := Roots[I] + '\';
    { Metinsel onek benzeri ('C:\Program Files Sahte\...') buradan GECEMEZ:
      ayirici ile birlikte karsilastirilir. }
    if CompareText(Copy(Canon, 1, Length(Root)), Root) = 0 then begin
      Result := True;
      exit;
    end;
  end;
end;

function ChainIsReparseFree(const Path: string; var Reason: string): Boolean;
var
  Cur, Prev: string;
  IsRep: Boolean;
begin
  Result := False;
  Cur := Path;
  while Trim(Cur) <> '' do begin
    if not PathIsReparse(Cur, IsRep) then begin
      Reason := 'reparse point durumu okunamadi: ' + Cur;
      exit;
    end;
    if IsRep then begin
      Reason := 'yol zincirinde junction/symlink var: ' + Cur;
      exit;
    end;
    Prev := Cur;
    Cur := ExtractFileDir(Cur);
    if CompareText(Cur, Prev) = 0 then break;
    if Length(Cur) <= 2 then break;
  end;
  Result := True;
end;

{ Verilen EXE, ONLOGON + HIGHEST goreve baglanabilecek kadar korunuyor mu? }
function PathIsVerifiedInstall(const Exe: string; var Reason: string): Boolean;
var
  Canon: string;
  Roots: TArrayOfString;
begin
  Result := False;
  Reason := '';
  if not PathCanonical(Exe, Canon) then begin
    Reason := 'yol canonical hale getirilemedi veya mevcut degil: ' + Exe;
    exit;
  end;
  if not ProgramFilesRoots(Roots) then begin
    Reason := 'gercek Program Files kokleri okunamadi';
    exit;
  end;
  if not PathIsUnderRoot(Canon, Roots) then begin
    Reason := 'hedef gercek Program Files altinda degil: ' + Canon;
    exit;
  end;
  if not ChainIsReparseFree(Canon, Reason) then exit;
  if not LocationIsAclProtected(Canon, Reason) then exit;
  if not LocationIsAclProtected(ExtractFileDir(Canon), Reason) then exit;
  Result := True;
end;
{ ===== DPORT SAFE TARGET END ===== }

{ ─────────────────────────────────────────────────────────────────────────
  Logon failsafe gorevi — kurulum/guncelleme gecisi (F2 kapanisi)

  SORUN: postinstall "DPort'u baslat" adimi ISTEGE BAGLI ve silent kurulumda
  atlanir. Kullanici yeni surumu hic calistirmadan oturumu kapatirsa, ONCEKI
  surumden kalmis ve YAZILABILIR bir hedefi gosteren DPortHostsFailsafe gorevi
  bir sonraki logon'da HIGHEST yetkiyle calisirdi.

  GUNCEL MODEL: gorev KALICI DEGILDIR. Yalnizca DPort'un isaretli hosts
  yonlendirmesi aktif olabilecegi surece var olur; uygulama yonlendirmeyi
  yazmadan hemen once kurar, temizledigi anda kaldirir. Kurulum, hosts
  DOGRULANMIS bicimde temizse GOREV OLUSTURMAZ; yalnizca yonlendirme
  temizlenemediginde DOGRULANMIS hedefe guvenli bir kurtarma gorevi kurar.

  COZUM (her normal / upgrade / silent kurulumda, secenege BAGLI OLMADAN):
    1. Onceki surumden kalmis olabilecek isaretli hosts blogu TEMIZLENIR.
       Gorev ancak yonlendirme gercekten yoksa gereksizdir; korlemesine
       silinirse temizlenmemis bir yonlendirme temizleyicisiz kalirdi.
    2. Gorev(ler) hosts SONUCUNA ve KAYITLI HEDEFE gore uzlastirilir
       (ReconcileFailsafeTask). hosts temizlenemediyse gorev korlemesine
       KORUNMAZ: hedefi okunur, dogrulanir; yalnizca korumali
       <app>\DPort.exe --cleanup-hosts hedefi korunabilir, digerleri guvenli
       gorevle DEGISTIRILIR.
    3. Basarisizlik SESSIZCE YUTULMAZ: Setup log'una yazilir, etkilesimli
       kurulumda hata kutusu gosterilir ve kurulum RaiseException ile
       basarisiz olur (silent upgrade'de de sifir-disi cikis kodu).
  ───────────────────────────────────────────────────────────────────────── }

function TaskExists(const Name: string): Boolean;
var
  Code: Integer;
begin
  Result := False;
  if Exec(ExpandConstant('{cmd}'),
          '/C schtasks /Query /TN "' + Name + '" >nul 2>&1',
          '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Result := (Code = 0);
end;

{ ── Gorev katmani ILKELLERI ───────────────────────────────────────────────
  Asagidaki isaretli KARAR blogu yalnizca bu uc rutini kullanir. Testler ayni
  karar blogunu ayiklayip SAHTE ilkellerle derleyip calistirir; boylece mantik
  gercek schtasks'a dokunmadan dogrulanir. }

{ Gorevi siler ve /Query ile GERCEKTEN gittigini dogrular.
  Gorev zaten yoksa True (silinecek bir sey yok; schtasks bu durumda sifir-disi
  kod dondurur, bu bir HATA DEGILDIR). }
function TaskDeleteVerified(const Name: string): Boolean;
var
  Code: Integer;
begin
  if not TaskExists(Name) then begin
    Result := True;
    exit;
  end;
  Exec(ExpandConstant('{cmd}'),
       '/C schtasks /Delete /TN "' + Name + '" /F >nul 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := not TaskExists(Name);
end;

{ Gorevin TAM tanimini XML olarak dondurur.
  Donus False = gorev yok VEYA tanim okunamadi/bozuk (ikisi de ayni sonuca
  goturur: guvenli sayilmaz). Tek tek alan okumak yerine TUM tanim dondurulur;
  dogrulamayi karar blogu yapar (bkz. TaskDefinitionIsSafe): boylece ikinci bir
  <Exec> eylemi veya yinelenmis <Command> gizlenemez.
  XML dili notrdur; /FO LIST ciktisi YERELLESTIGI icin kullanilmaz.
  GUVENLIK: XML kullanici-yazilabilir TEMP dosyasina yonlendirilmez; schtasks
  stdout'u dogrudan Inno pipe'iyle yakalanir ve ayni bellek degeri dogrulanir. }
function TaskQueryXml(const Name: string; var Xml: string): Boolean;
var
  Code: Integer;
  Output: TExecOutput;
begin
  Result := False;
  Xml := '';
  try
    if not ExecAndCaptureOutput(
      ExpandConstant('{sys}\schtasks.exe'),
      '/Query /TN "' + Name + '" /XML',
      '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code, Output) then exit;
  except
    Log('DPort: gorev XML ciktisi yakalanamadi: ' + GetExceptionMessage);
    exit;
  end;
  if (Code <> 0) or Output.Error then exit;
  if Trim(CapturedLinesText(Output.StdErr)) <> '' then exit;
  Xml := CapturedLinesText(Output.StdOut);
  Result := Trim(Xml) <> '';
end;

{ ONLOGON + HIGHEST gorevi olusturur. cmd.exe ARACILIGI OLMADAN calistirilir:
  ic tirnaklarin cmd tarafindan yeniden yorumlanmasi engellenir. }
function TaskCreateLogon(const Name, Exe, Args: string): Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\schtasks.exe'),
    '/Create /TN "' + Name + '" /TR "\"' + Exe + '\" ' + Args
    + '" /SC ONLOGON /RL HIGHEST /F',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

{ ===== DPORT FAILSAFE TASK BEGIN ===== }
{ Gorev yasam dongusunun TEK karar noktasi (installer tarafi).

  Kural: ONLOGON + HIGHEST bir gorev, YALNIZCA korumali kurulum hedefini
  (<app>\DPort.exe --cleanup-hosts) gosterebilir. Kullanici-yazilabilir,
  okunamayan, bozuk veya yanlis argumanli hicbir tanim ayakta BIRAKILMAZ -
  hosts temizligi basarisiz olsa bile. Aksi halde standart kullanici, her
  oturum acilista YUKSEK yetkiyle calisan bir hedefi degistirerek kalici,
  UAC'siz yetki yukseltmesi elde ederdi.

  Bu blok yalnizca TaskQuery / TaskDeleteVerified / TaskCreateLogon
  ilkellerine baglidir; testler ayni kodu sahte ilkellerle calistirir. }
const
  TASK_NAME       = 'DPortHostsFailsafe';
  LEGACY_TASK     = 'DiscordConnectHostsFailsafe';
  FS_CLEANUP_ARGS = '--cleanup-hosts';

function CountOccurrences(const Haystack, Needle: string): Integer;
var
  P, Start: Integer;
begin
  Result := 0;
  if (Needle = '') or (Haystack = '') then exit;
  Start := 1;
  while Start <= Length(Haystack) do begin
    P := Pos(Needle, Copy(Haystack, Start, Length(Haystack) - Start + 1));
    if P = 0 then exit;
    Result := Result + 1;
    Start := Start + P + Length(Needle) - 1;
  end;
end;

{ Etiketin TAM OLARAK BIR kez gectigini dogrular ve degerini dondurur.
  Yinelenmis etiket (or. iki <Command>) REDDEDILIR; "son goruleni al"
  davranisi, once zararli sonra masum gorunen bir tanimi guvenli gosterirdi. }
function ExtractSingleTag(const Xml, Tag: string; var Value: string): Boolean;
var
  OpenT, CloseT: string;
  P, Q: Integer;
begin
  Result := False;
  Value := '';
  OpenT := '<' + Tag + '>';
  CloseT := '</' + Tag + '>';
  if CountOccurrences(Xml, OpenT) <> 1 then exit;
  if CountOccurrences(Xml, CloseT) <> 1 then exit;
  P := Pos(OpenT, Xml) + Length(OpenT);
  Q := Pos(CloseT, Xml);
  if Q <= P then exit;
  Value := Trim(Copy(Xml, P, Q - P));
  Result := True;
end;

{ XML entity cozumu. YALNIZCA bes standart adlandirilmis entity desteklenir;
  sayisal (&#65;) veya bilinmeyen entity FAIL CLOSED'dur. Boylece ayni girdi
  her zaman ayni sonucu verir (deterministik). }
function XmlDecode(const S: string; var Decoded: string): Boolean;
var
  I, P, Found: Integer;
  Ent, C: string;
begin
  Result := False;
  Decoded := '';
  I := 1;
  while I <= Length(S) do begin
    C := Copy(S, I, 1);
    if C <> '&' then begin
      Decoded := Decoded + C;
      I := I + 1;
    end else begin
      Found := 0;
      P := I + 1;
      while (P <= Length(S)) and (P <= I + 8) do begin
        if Copy(S, P, 1) = ';' then begin
          Found := P;
          break;
        end;
        P := P + 1;
      end;
      if Found = 0 then exit;
      Ent := Lowercase(Copy(S, I, Found - I + 1));
      if Ent = '&amp;' then Decoded := Decoded + '&'
      else if Ent = '&lt;' then Decoded := Decoded + '<'
      else if Ent = '&gt;' then Decoded := Decoded + '>'
      else if Ent = '&quot;' then Decoded := Decoded + '"'
      else if Ent = '&apos;' then Decoded := Decoded + ''''
      else exit;
      I := Found + 1;
    end;
  end;
  Result := True;
end;

{ Gorevin TAM tanimi beklenen guvenli tanim mi?

  Kabul icin HEPSI gerekli:
    - tam olarak BIR <Exec> eylemi (baska eylem turu hic yok)
    - tam olarak BIR <Command> ve BIR <Arguments>
    - tam olarak BIR trigger, o da <LogonTrigger>
    - <RunLevel> = HighestAvailable
    - Command (entity cozulmus) = korumali kurulum hedefi
    - Arguments (entity cozulmus) = --cleanup-hosts
  Eksik, fazladan, bozuk veya okunamayan tanim REDDEDILIR. }
function TaskDefinitionIsSafe(const Xml, SafeExe: string): Boolean;
var
  Value, Decoded: string;
begin
  Result := False;
  if Trim(Xml) = '' then exit;

  { Tam olarak bir Exec eylemi; baska eylem turu kabul edilmez. }
  if CountOccurrences(Xml, '<Exec>') <> 1 then exit;
  if CountOccurrences(Xml, '</Exec>') <> 1 then exit;
  if CountOccurrences(Xml, '<ComHandler') > 0 then exit;
  if CountOccurrences(Xml, '<SendEmail') > 0 then exit;
  if CountOccurrences(Xml, '<ShowMessage') > 0 then exit;

  { Tam olarak bir trigger, o da ONLOGON. ('Trigger>' sayisi = ac + kapa) }
  if CountOccurrences(Xml, '<LogonTrigger>') <> 1 then exit;
  if CountOccurrences(Xml, 'Trigger>') <> 2 then exit;

  { Yetki seviyesi }
  if not ExtractSingleTag(Xml, 'RunLevel', Value) then exit;
  if CompareText(Value, 'HighestAvailable') <> 0 then exit;

  { Hedef }
  if not ExtractSingleTag(Xml, 'Command', Value) then exit;
  if not XmlDecode(Value, Decoded) then exit;
  if CompareText(Trim(RemoveQuotes(Trim(Decoded))), Trim(SafeExe)) <> 0 then exit;

  { Argumanlar }
  if not ExtractSingleTag(Xml, 'Arguments', Value) then exit;
  if not XmlDecode(Value, Decoded) then exit;
  Result := CompareText(Trim(RemoveQuotes(Trim(Decoded))), FS_CLEANUP_ARGS) = 0;
end;

{ Kayitli gorev, korumali kurulum hedefiyle BIREBIR esliyor mu?
  Gorev yoksa veya tanimi okunamiyorsa False (fail closed). }
function FailsafeTaskIsSafe(const SafeExe: string): Boolean;
var
  Xml: string;
begin
  Result := False;
  if not TaskQueryXml(TASK_NAME, Xml) then exit;
  Result := TaskDefinitionIsSafe(Xml, SafeExe);
end;

{ Donus: "ayakta guvensiz gorev yok" GARANTI edilebiliyor mu.
  False ise Problem doludur ve cagiran bunu SESSIZCE YUTMAMALIDIR. }
function ReconcileFailsafeTask(HostsCleaned: Boolean; const SafeExe: string;
                               var Problem: string): Boolean;
var
  Reason: string;
begin
  Problem := '';
  Reason := '';
  Result := False;

  { 1) Eski adlar hosts sonucundan BAGIMSIZ olarak HER ZAMAN kaldirilir:
       onlarin hedefi bizim protokolumuzle dogrulanmaz, dolayisiyla guvenli
       kabul edilemezler. }
  if not TaskDeleteVerified(LEGACY_TASK) then begin
    Problem := 'Eski "' + LEGACY_TASK + '" oturum acilis gorevi kaldirilamadi.';
    exit;
  end;

  { 2) hosts temizligi DOGRULANDI -> kurtarilacak yonlendirme yok, gorev de
       gereksiz. }
  if HostsCleaned then begin
    if not TaskDeleteVerified(TASK_NAME) then begin
      Problem := '"' + TASK_NAME + '" gorevi kaldirilamadi.';
      exit;
    end;
    Result := True;
    exit;
  end;

  { 3) hosts kalintisi VAR -> kurtarma gorevi GEREKLI. Ama once HEDEFIN KENDISI
       bagimsiz olarak dogrulanmali: dogrulanmamis bir EXE ne goreve hedef
       yapilir ne de ona isaret eden bir gorev korunur. `FileExists` burada
       kullanilmaz; kullanici-yazilabilir bir DPort.exe de "vardir". }
  if not PathIsVerifiedInstall(SafeExe, Reason) then begin
    { Guvensiz hedefe isaret ediyor olabilecek gorev ayakta BIRAKILMAZ. }
    if not TaskDeleteVerified(TASK_NAME) then
      Problem := 'Kurulum hedefi dogrulanamadi (' + Reason
                 + ') VE mevcut oturum acilis gorevi kaldirilamadi.'
    else
      Problem := 'Kurulum hedefi HIGHEST gorev icin dogrulanamadi: ' + Reason;
    exit;
  end;

  { 4) Ayakta olan TAM tanim beklenen guvenli tanimsa korunur. }
  if FailsafeTaskIsSafe(SafeExe) then begin
    Log('DPort FAILSAFE: mevcut gorev korumali hedefi gosteriyor, KORUNDU');
    Result := True;
    exit;
  end;

  { 5) Eksik / okunamayan / bozuk / fazladan eylemli / yanlis argumanli:
       once KALDIR, sonra DOGRULANMIS hedefle YENIDEN kur. }
  Log('DPort FAILSAFE: gorev dogrulanamadi -> guvenli hedefle DEGISTIRILIYOR');
  if not TaskDeleteVerified(TASK_NAME) then begin
    Problem := 'Guvenilmeyen "' + TASK_NAME + '" gorevi kaldirilamadi.';
    exit;
  end;
  if not TaskCreateLogon(TASK_NAME, SafeExe, FS_CLEANUP_ARGS) then begin
    Problem := 'Guvenli kurtarma gorevi olusturulamadi.';
    exit;
  end;

  { 6) GERI OKUMA: gercek tanim yeniden okunur ve AYNI kontrollerden gecirilir. }
  if not FailsafeTaskIsSafe(SafeExe) then begin
    TaskDeleteVerified(TASK_NAME);
    Problem := 'Olusturulan kurtarma gorevi geri okundugunda DOGRULANAMADI.';
    exit;
  end;
  Result := True;
end;
{ ===== DPORT FAILSAFE TASK END ===== }

procedure DropFailsafeTaskAfterHostsCleanup();
var
  HostsCleaned: Boolean;
  SafeExe, Problem: string;
begin
  { 1) Onceki surumden kalmis isaretli hosts blogunu temizle. }
  HostsCleaned := CleanHostsBlock(HostsFilePath());
  if not HostsCleaned then
    Log('DPort FAILSAFE: hosts yonlendirmesi temizlenemedi/dogrulanamadi -> '
        + 'guvenli kurtarma gorevi GEREKLI');

  { 2) Hedefin GUVENLI olup olmadigina ReconcileFailsafeTask karar verir; oradaki
       PathIsVerifiedInstall canonical yolu, gercek Program Files kokunu,
       reparse point'siz zinciri ve ACL/sahiplik durumunu dogrular. Burada
       `FileExists` gibi bir "guvenlik" kapisi YOKTUR: dosyanin var olmasi onu
       guvenli YAPMAZ (var olmamasi da zaten dogrulamayi dusurur). }
  SafeExe := ExpandConstant('{app}\{#MyAppExeName}');
  if ReconcileFailsafeTask(HostsCleaned, SafeExe, Problem) then begin
    { NOT: Bir satir '[' ile BASLAYAMAZ; ISCC bunu bolum etiketi sanar. }
    Log('DPort: failsafe gorev uzlasmasi TAMAM (hosts temiz='
        + IntToStr(Integer(HostsCleaned)) + ')');
    if not HostsCleaned and not WizardSilent then
      MsgBox('DPort kuruldu, ancak hosts dosyasindaki eski Discord'
             + ' yonlendirmesi temizlenemedi.' + #13#10#13#10
             + 'Guvenli bir oturum acilis temizlik gorevi kuruldu:'
             + ' yonlendirme bir sonraki oturum acilisinda otomatik'
             + ' temizlenecek.' + #13#10#13#10
             + 'Isterseniz DPort''u calistirip "Normale Don" ile hemen'
             + ' temizleyebilirsiniz.', mbInformation, MB_OK);
    exit;
  end;

  { 2) Guvenlik garantisi verilemedi: SESSIZCE BASARILI SAYMA.
       Etkilesimli kurulumda aciklayici kutu, her kurulumda (silent dahil)
       RaiseException ile gorunur basarisizlik + sifir-disi cikis kodu. }
  Log('DPort FAILSAFE HATASI: ' + Problem);
  if not WizardSilent then
    MsgBox('DPort guvenli kurtarma gorevini kuramadi:' + #13#10#13#10
           + Problem + #13#10#13#10
           + 'Kurulum guvenlik nedeniyle durduruluyor. Gorev Zamanlayici''da'
           + ' "' + TASK_NAME + '" ve "' + LEGACY_TASK + '" gorevlerini elle'
           + ' silip kurulumu tekrar deneyin.', mbError, MB_OK);
  RaiseException('DPort guvenli kurtarma gorevi kurulamadi: ' + Problem);
end;

{ Kisayol/masaustu ikonu bos gorunmesin diye kurulum sonunda shell ikon
  onbellegini yenilenmeye zorlar (dosya sistemi degisikligi yayinlar). }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    { Dosyalar kuruldu; hosts temizligi + gorev kaldirma burada yapilir. Istege bagli
      "DPort'u baslat" secenegine BAGLI DEGILDIR ve silent kurulumda da calisir. }
    DropFailsafeTaskAfterHostsCleanup();
    SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    { 1) calisan DPort'u kapat }
    Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM ' + '{#MyAppExeName}',
         '', SW_HIDE, ewWaitUntilTerminated, Code);
    { 2) hosts yonlendirmesini temizle }
    if not CleanHostsBlock(HostsFilePath()) then begin
      Log('DPort KALDIRMA: hosts yonlendirmesi temizlenemedi/dogrulanamadi');
      if not UninstallSilent then
        MsgBox('DPort kaldiriliyor, ancak hosts dosyasindaki Discord'
               + ' yonlendirmesi temizlenemedi.' + #13#10#13#10
               + 'Bu satirlar kalirsa Discord ve discord.com acilmaz. Lutfen'
               + ' %WinDir%\System32\drivers\etc\hosts dosyasindaki'
               + ' "DPort Discord unblock" blogunu elle silin.', mbError, MB_OK);
    end;
    { 3) logon guvenlik gorevini sil. KALDIRMA yolunda bu KOSULSUZDUR: hedef exe
         birazdan silinecegi icin gorev zaten calisamaz; ayakta kalmasi yalnizca
         her oturum acilista basarisiz bir HIGHEST gorev birakirdi. }
    Exec(ExpandConstant('{cmd}'), '/C schtasks /Delete /TN "DPortHostsFailsafe" /F',
         '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{cmd}'), '/C schtasks /Delete /TN "DiscordConnectHostsFailsafe" /F',
         '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;
