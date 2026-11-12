@echo off
cd /d "%~dp0"
set PY=py
%PY% --version >nul 2>&1 || set PY=python
%PY% --version >nul 2>&1 || goto :nopython
%PY% -m pip install --upgrade pip pyinstaller psutil || goto :err
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name PCSpecs --icon pcspecs.ico --add-data "pcspecs.ico;." pcspecs.py || goto :err
copy /y dist\PCSpecs.exe PCSpecs.exe >nul
echo.
echo DONE: PCSpecs.exe is next to this file.
explorer /select,"%~dp0PCSpecs.exe"
pause
exit /b 0
:nopython
echo Python not found. Install it from python.org (tick "Add python.exe to PATH").
pause
exit /b 1
:err
echo Build failed, see messages above.
pause
exit /b 1
