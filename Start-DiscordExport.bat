@echo off
rem Startet Discord-Export. Die Oberfläche öffnet sich im Browser.
rem Dieses Fenster offen lassen, solange du das Programm nutzt.
cd /d "%~dp0"
py -3 discord_export.py %*
if errorlevel 1 pause
