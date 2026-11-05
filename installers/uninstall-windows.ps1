[CmdletBinding()]
param([string]$InstallDirectory="$env:ProgramFiles\ActionsRunnerConsole",[string]$PythonExe='python.exe')
$ErrorActionPreference='Stop'
foreach($name in @('ActionsRunnerConsoleDisplay','ActionsRunnerConsoleCollector')){
  if(Get-ScheduledTask $name -ErrorAction SilentlyContinue){
    Stop-ScheduledTask $name
    Unregister-ScheduledTask $name -Confirm:$false
  }
}
& $PythonExe "$InstallDirectory\run.py" --config "$InstallDirectory\config.json" uninstall-hooks
if($LASTEXITCODE -ne 0){throw 'Could not restore hooks'}
Write-Host 'Tasks removed; prior hooks restored. Restart the GitHub runner when idle.'
Write-Host 'Files, logs, and the account batch-logon right were retained; other tasks may depend on them.'
