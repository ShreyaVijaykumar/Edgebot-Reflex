@echo off
setlocal EnableDelayedExpansion

echo.
echo ============================================================
echo  EdgeBot Reflex - ESP32 Build Script
echo ============================================================
echo.

REM ── Locate arduino-cli ──────────────────────────────────────
REM Check local folder first (most likely for this project),
REM then fall back to PATH.

IF EXIST "%~dp0arduino-cli.exe" (
    SET ARDUINO_CLI=%~dp0arduino-cli.exe
    echo [OK] Using arduino-cli.exe found in wokwi\ folder.
) ELSE (
    where arduino-cli >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        SET ARDUINO_CLI=arduino-cli
        echo [OK] Using arduino-cli found in system PATH.
    ) ELSE (
        echo [ERROR] arduino-cli.exe not found.
        echo         Place arduino-cli.exe in the wokwi\ folder and re-run.
        echo         Download from: https://arduino.cc/en/software
        pause & exit /b 1
    )
)

echo        Path: !ARDUINO_CLI!
echo.

REM ── Confirm sketch.ino exists ────────────────────────────────
IF NOT EXIST "%~dp0sketch.ino" (
    echo [ERROR] sketch.ino not found.
    echo         Run this .bat from inside the wokwi\ folder.
    pause & exit /b 1
)

REM ── Step 1: Init config ──────────────────────────────────────
echo [1/4] Initialising arduino-cli config...
"!ARDUINO_CLI!" config init --overwrite >nul 2>&1
echo       Done.

REM ── Step 2: Add ESP32 board URL ─────────────────────────────
echo [2/4] Setting ESP32 board manager URL...
"!ARDUINO_CLI!" config set board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Could not set board URL. Check internet connection.
    pause & exit /b 1
)

echo       Updating board index (needs internet, ~30 seconds)...
"!ARDUINO_CLI!" core update-index
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Board index update failed. Check internet connection.
    pause & exit /b 1
)

REM ── Step 3: Install ESP32 core ───────────────────────────────
echo [3/4] Installing ESP32 core (first run ~2-5 min, ~150MB)...
echo       If already installed this will skip automatically.
"!ARDUINO_CLI!" core install esp32:esp32
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] ESP32 core install failed.
    echo         - Check internet / firewall
    echo         - Try running this .bat as Administrator (right-click)
    pause & exit /b 1
)
echo       ESP32 core ready.

REM ── Step 4: Compile sketch ───────────────────────────────────
echo.
echo [4/4] Compiling sketch.ino (30-90 seconds)...
echo       Full compiler output shown below so errors are visible:
echo       ----------------------------------------------------

IF NOT EXIST "%~dp0build" mkdir "%~dp0build"

"!ARDUINO_CLI!" compile ^
    --fqbn esp32:esp32:esp32 ^
    --output-dir "%~dp0build" ^
    --verbose ^
    "%~dp0sketch.ino"

SET COMPILE_RESULT=%ERRORLEVEL%
echo       ----------------------------------------------------

IF %COMPILE_RESULT% NEQ 0 (
    echo.
    echo [ERROR] Compilation failed. Read the output above for the exact error.
    echo.
    echo Common fixes:
    echo   "was not declared in this scope"  -^> run: .\arduino-cli.exe core upgrade esp32:esp32
    echo   "no such file or directory"       -^> ESP32 core not fully installed, re-run this script
    echo   "'startsWith' is not a member"    -^> run: .\arduino-cli.exe core upgrade esp32:esp32
    echo.
    pause & exit /b 1
)

REM ── Success ──────────────────────────────────────────────────
echo.
echo ============================================================
echo  BUILD SUCCESSFUL
echo ============================================================
echo.
echo Firmware is at:
echo   wokwi\build\esp32.esp32.esp32\sketch.ino.elf
echo.
echo Next steps:
echo   1. Open the wokwi\ folder in VSCode (not the parent folder)
echo        File ^> Open Folder ^> select wokwi\
echo   2. First time only: F1 ^> "Wokwi: Request Free License"
echo   3. Start simulator: F1 ^> "Wokwi: Start Simulator"
echo   4. Open a second terminal and run:
echo        cd ..
echo        python edgebot_bridge.py
echo.
pause