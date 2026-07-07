@echo off
title DPort - Temizleyici

:: UAC (Yonetici) izni kontrolu
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo Yonetici izinleri isteniyor...
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "cmd.exe", "/c ""%~s0""", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B
)
pushd "%CD%"
CD /D "%~dp0"

echo ==========================================
echo   DPort - Proje Temizleyici
echo ==========================================
echo.
echo [*] Derleme artiklari, gecici dosyalar ve EXE'ler siliniyor...
echo.

:: Eger aciksa DPort.exe'yi zorla kapat ki dist klasoru silinebilsin
taskkill /f /im "DPort.exe" >nul 2>&1
ping 127.0.0.1 -n 2 >nul

:: Klasorleri sil
if exist "build" (
    rmdir /s /q "build"
    echo [OK] build/ klasoru silindi.
)

if exist "dist" (
    rmdir /s /q "dist"
    echo [OK] dist/ klasoru silindi.
)

:: Cache dosyalarini sil
for /d /r . %%d in (__pycache__) do @if exist "%%d" (
    rmdir /s /q "%%d" >nul 2>&1
    echo [OK] %%d temizlendi.
)

if exist "DPort.exe" (
    del /q "DPort.exe"
    echo [OK] Ana dizindeki .exe artiklari silindi.
)

echo.
echo ==========================================
echo   Temizlik basariyla tamamlandi!
echo   Masaustu projeniz tertemiz hale geldi.
echo ==========================================
pause
