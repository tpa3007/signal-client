@echo off
REM Wrapper for the Signal dashboard sync daemon (used by Task Scheduler).
REM Uses bare "python" (on user PATH) so no non-ASCII path is embedded.
cd /d C:\Signal\bot
echo ==== %DATE% %TIME% ==== >> sync_daemon.log
python sync_daemon.py --once --push >> sync_daemon.log 2>&1
echo exit=%ERRORLEVEL% >> sync_daemon.log
