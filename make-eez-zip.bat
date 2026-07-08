@echo off
set SRC=%~dp0eezstudio
set OUT=%~dp0ea-ps2000-series-1.0.29.zip
set TMP=%~dp0_eez_tmp

echo Creating EEZ Studio extension ZIP...

:: Copy to temp folder to avoid ProtonDrive file locks on source
if exist "%TMP%" rd /s /q "%TMP%"
mkdir "%TMP%"
copy /y "%SRC%\package.json" "%TMP%\" >nul
copy /y "%SRC%\image.png"    "%TMP%\" >nul
copy /y "%SRC%\ea_ps2342.idf" "%TMP%\" >nul
copy /y "%SRC%\ea_ps2342.sdl" "%TMP%\" >nul

if exist "%OUT%" del "%OUT%"
powershell -NoProfile -Command "Compress-Archive -Path '%TMP%\*' -DestinationPath '%OUT%' -Force"

rd /s /q "%TMP%"

if exist "%OUT%" (
    echo.
    echo Created: %OUT%
    echo.
    echo In EEZ Studio:
    echo   Home ^> Extensions ^> Install ^> choose the zip above
    echo.
) else (
    echo ERROR: ZIP was not created.
)
pause
