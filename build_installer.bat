@echo off
REM Step 2 (optional, command line): compiles installer\jarvis.iss -> installer\Output\Jarvis_Setup.exe
cd /d "%~dp0"
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (echo Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php & exit /b 1)
%ISCC% installer\jarvis.iss
