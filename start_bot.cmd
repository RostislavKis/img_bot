@echo off
REM РЎРєСЂРёРїС‚ Р·Р°РїСѓСЃРєР° Telegram Р±РѕС‚Р°
REM РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ: start_bot.cmd [quiet]

setlocal enabledelayedexpansion

set BOT_DIR=%~dp0
set VENV_DIR=%BOT_DIR%.venv
set MODE=%1

echo.
echo =========================================
echo IMG_BOT Р·Р°РїСѓСЃРєР°РµС‚СЃСЏ...
echo =========================================
echo Р”РёСЂРµРєС‚РѕСЂРёСЏ: %BOT_DIR%
echo Р’РёСЂС‚СѓР°Р»СЊРЅРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ: %VENV_DIR%
echo.

if not exist "%VENV_DIR%" (
    echo.
    echo РћРЁРР‘РљРђ: Р’РёСЂС‚СѓР°Р»СЊРЅРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ РІ %VENV_DIR%
    echo РџРѕР¶Р°Р»СѓР№СЃС‚Р°, СЃРѕР·РґР°Р№С‚Рµ РІРёСЂС‚СѓР°Р»СЊРЅРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM РђРєС‚РёРІРёСЂСѓРµРј РІРёСЂС‚СѓР°Р»СЊРЅРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ
call "%VENV_DIR%\Scripts\activate.bat"

if /i "%MODE%"=="quiet" (
    REM Р—Р°РїСѓСЃРє РІ С„РѕРЅРµ
    start "" "%VENV_DIR%\Scripts\python.exe" main.py
    echo Р‘РѕС‚ Р·Р°РїСѓС‰РµРЅ РІ С„РѕРЅРѕРІРѕРј СЂРµР¶РёРјРµ.
    timeout /t 2 /nobreak
) else (
    REM Р—Р°РїСѓСЃРє СЃ РІРёРґРёРјРѕР№ РєРѕРЅСЃРѕР»СЊСЋ
    "%VENV_DIR%\Scripts\python.exe" main.py
)

endlocal
