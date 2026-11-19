@echo off
REM Step 1: builds dist\Jarvis\Jarvis.exe (run this on Windows, in the project folder)
cd /d "%~dp0"
python -m venv .buildvenv || goto :err
call .buildvenv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-optional.txt pyinstaller || goto :err
pyinstaller --noconfirm --clean jarvis.spec || goto :err
echo.
echo DONE: dist\Jarvis\Jarvis.exe
echo Next: open installer\jarvis.iss in Inno Setup and press Compile (or run build_installer.bat)
exit /b 0
:err
echo BUILD FAILED
exit /b 1
