@echo off
title DPort - Build
echo.
echo ==========================================
echo   DPort - EXE Derleme
echo ==========================================
echo.

REM Python kontrolu
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadi!
    pause
    exit /b 1
)
python --version
echo [OK] Python kurulu.
echo.

REM PyInstaller kontrolu
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [ ] PyInstaller bulunamadi, yukleniyor...
    pip install pyinstaller --quiet
    if %errorlevel% neq 0 (
        echo [HATA] PyInstaller yuklenemedi!
        pause
        exit /b 1
    )
    echo [OK] PyInstaller yuklendi.
) else (
    echo [OK] PyInstaller zaten yuklu.
)

REM Bagimlilik kontrolu
echo.
echo [*] Bagimliliklari kontrol ediliyor...

pip show customtkinter >nul 2>&1
if %errorlevel% neq 0 ( pip install customtkinter --quiet && echo [OK] customtkinter yuklendi. ) else ( echo [OK] customtkinter yuklu. )

pip show Pillow >nul 2>&1
if %errorlevel% neq 0 ( pip install Pillow --quiet && echo [OK] Pillow yuklendi. ) else ( echo [OK] Pillow yuklu. )

pip show pystray >nul 2>&1
if %errorlevel% neq 0 ( pip install pystray --quiet && echo [OK] pystray yuklendi. ) else ( echo [OK] pystray yuklu. )

echo.

REM Ikon kontrolu
set ICON_ARG=
if exist "app\assets\icon.ico" (
    echo [OK] app\assets\icon.ico bulundu, kullanilacak.
    set ICON_ARG=--icon="app\assets\icon.ico"
) else (
    echo [!] app\assets\icon.ico bulunamadi, ikonsuz devam ediliyor.
)

echo.
echo [*] Derleme basliyor, lutfen bekleyin...
echo.

pyinstaller ^
    --onefile ^
    --noconsole ^
    --name "DPort" ^
    --uac-admin ^
    --noupx ^
    %ICON_ARG% ^
    --exclude-module "numpy" ^
    --exclude-module "pandas" ^
    --add-binary "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python3.dll;." ^
    --add-binary "%LOCALAPPDATA%\Python\pythoncore-3.14-64\vcruntime140.dll;." ^
    --add-binary "%LOCALAPPDATA%\Python\pythoncore-3.14-64\vcruntime140_1.dll;." ^
    --add-data "app\assets;assets" ^
    --hidden-import "customtkinter" ^
    --hidden-import "PIL" ^
    --hidden-import "pystray" ^
    --collect-all "customtkinter" ^
    app\main.py

if %errorlevel% neq 0 (
    echo.
    echo [HATA] Derleme basarisiz!
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   Derleme tamamlandi!
echo   EXE: dist\DPort.exe
echo ==========================================
echo.

pause
