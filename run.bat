@echo off
rem Run the calculator without having to remember an interpreter path.
rem
rem     run.bat                 best mix (the default)
rem     run.bat report          per-stake table
rem     run.bat stake 200NL     one stake in detail
rem     run.bat mix --charts    + write the PNGs to output\
rem
rem Picks the first interpreter that exists: this repo's own .venv if you ever
rem make one, otherwise the nemesis-mvp venv next door (which has matplotlib),
rem otherwise whatever `py` resolves to. Only the charts need matplotlib - the
rem text commands run on bare Python 3.11+.

setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%HERE%..\nemesis-mvp\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=py"

pushd "%HERE%"
"%PY%" run.py %*
set "CODE=%ERRORLEVEL%"
popd

exit /b %CODE%
