@echo off
chcp 65001 >nul
title DPort - Calistirici
set "ROOT=%~dp0.."
pushd "%ROOT%" || exit /b 1
echo.
echo ==========================================
echo   DPort - Ortam Kontrolu
echo ==========================================
echo.

REM Python kurulu mu?
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadi!
    echo        https://python.org adresinden Python 3.10+ yukleyin.
    echo        Kurulum sirasinda "Add Python to PATH" secin.
    echo.
    pause
    exit /b 1
)
python --version
echo [OK] Python kurulu.
echo.

REM Kutuphaneleri kontrol et ve gerekirse yukle
echo [*] Kutuphaneler kontrol ediliyor...
echo.

pip show customtkinter >nul 2>&1
if %errorlevel% neq 0 (
    echo [ ] customtkinter bulunamadi, yukleniyor...
    pip install customtkinter --quiet
    echo [OK] customtkinter yuklendi.
) else (
    echo [OK] customtkinter zaten yuklu.
)

pip show Pillow >nul 2>&1
if %errorlevel% neq 0 (
    echo [ ] Pillow bulunamadi, yukleniyor...
    pip install Pillow --quiet
    echo [OK] Pillow yuklendi.
) else (
    echo [OK] Pillow zaten yuklu.
)

pip show pystray >nul 2>&1
if %errorlevel% neq 0 (
    echo [ ] pystray bulunamadi, yukleniyor...
    pip install pystray --quiet
    echo [OK] pystray yuklendi.
) else (
    echo [OK] pystray zaten yuklu.
)

echo.
echo ==========================================
echo   Uygulama baslatiliyor...
echo ==========================================
echo.

REM Bu konsolu ACIK tut ki gelistirirken loglari canli gorebilesin.
REM (Derlenen dist\DPort.exe ise --noconsole ile konsolsuz calisir.)
python "app\main.py"
popd
