@echo off
chcp 65001 >nul
title DPort - Kurulum (Setup) Olustur
echo.
echo ==========================================
echo   DPort - Kurulum Dosyasi Olusturucu
echo ==========================================
echo.
echo [1/2] EXE derleniyor (PyInstaller)...
echo.

python -m PyInstaller DPort.spec --noconfirm --clean
if %errorlevel% neq 0 (
    echo.
    echo [HATA] EXE derlenemedi!
    pause
    exit /b 1
)
if not exist "dist\DPort.exe" (
    echo [HATA] dist\DPort.exe olusmadi!
    pause
    exit /b 1
)
echo.
echo [OK] dist\DPort.exe hazir.
echo.
echo [2/2] Kurulum (setup) olusturuluyor (Inno Setup)...
echo.

REM ISCC yolunu bul (Inno Setup 7 / 6)
set "ISCC="
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo [HATA] Inno Setup ISCC.exe bulunamadi!
    echo        https://jrsoftware.org/isdl.php adresinden Inno Setup kurun.
    pause
    exit /b 1
)

"%ISCC%" "DPort.iss"
if %errorlevel% neq 0 (
    echo.
    echo [HATA] Kurulum olusturulamadi!
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   TAMAMLANDI!
echo   Kurulum: installer\DPort-Setup-2.3.exe
echo ==========================================
echo.
pause
