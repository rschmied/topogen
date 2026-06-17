@echo off
REM TG-192 full cycle proof (cmd.exe). Set secrets below, then run from repo root.
REM Stages: offline gates -^> generate -^> cml2 apply -^> sync -^> nac apply -^> provision user
REM         -^> Jira READY dry-run -^> revoke user -^> terraform destroy
REM Keep lab for customer login test: add -SkipTeardown to the powershell line.

set TF_VAR_address=https://192.168.1.183
set TF_VAR_username=REPLACE_ME
set TF_VAR_password=REPLACE_ME
set TF_VAR_skip_verify=true
set VIRL2_URL=https://192.168.1.183
set VIRL2_USER=REPLACE_ME
set VIRL2_PASS=REPLACE_ME
set IOSXE_USERNAME=cisco
set IOSXE_PASSWORD=cisco

cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\validate-tg192-pipeline.ps1 -ProveCycle
exit /b %ERRORLEVEL%
