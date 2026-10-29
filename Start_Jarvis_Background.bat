@echo off
REM Starts Jarvis with no console window and no HUD - he just listens. Say "Jarvis, show yourself" to see him.
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw jarvis.py --background) || (start "" /min python jarvis.py --background)
