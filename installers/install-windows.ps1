[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$RunnerDirectory,
  [Parameter(Mandatory=$true)][PSCredential]$Credential,
  [string]$PythonExe = 'python.exe',
  [string]$InstallDirectory = "$env:ProgramFiles\ActionsRunnerConsole",
  [string]$DataDirectory = "$env:ProgramData\ActionsRunnerConsole",
  [switch]$GrantBatchLogonRight,
  [switch]$StartAtLogon,
  [switch]$ReplaceHooks,
  [switch]$RestartRunner
)
$ErrorActionPreference='Stop'
$admin=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(!$admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Run the installer as administrator; its tasks run as the supplied runner account.'}
$PythonExe=(Get-Command $PythonExe -ErrorAction Stop).Source
& $PythonExe -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
if($LASTEXITCODE -ne 0){throw 'Python 3.10+ required'}
$RunnerDirectory=(Resolve-Path $RunnerDirectory).Path
$InstallDirectory=[IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
$DataDirectory=[IO.Path]::GetFullPath($DataDirectory).TrimEnd('\')
if(!(Test-Path "$RunnerDirectory\_diag")){throw 'Start/configure the GitHub runner first (_diag is missing).'}
if($InstallDirectory -eq [IO.Path]::GetPathRoot($InstallDirectory).TrimEnd('\') -or $DataDirectory -eq [IO.Path]::GetPathRoot($DataDirectory).TrimEnd('\')){throw 'Do not use a drive root.'}
if($DataDirectory.StartsWith($RunnerDirectory+'\',[StringComparison]::OrdinalIgnoreCase) -or $DataDirectory.StartsWith($InstallDirectory+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Data must live outside the runner and program directories.'}
$account=$Credential.UserName
if($account.StartsWith('.\')){$account=$env:COMPUTERNAME+$account.Substring(1)}
if(!$account.Contains('\') -and !$account.Contains('@')){$account="$env:COMPUTERNAME\$account"}
$sid=([Security.Principal.NTAccount]::new($account)).Translate([Security.Principal.SecurityIdentifier]).Value
New-Item -ItemType Directory -Force $InstallDirectory,$DataDirectory | Out-Null
& icacls.exe $InstallDirectory /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*${sid}:(OI)(CI)RX" | Out-Null
if($LASTEXITCODE -ne 0){throw 'Cannot protect installation directory'}
& icacls.exe $DataDirectory /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*${sid}:(OI)(CI)M" | Out-Null
if($LASTEXITCODE -ne 0){throw 'Cannot protect data directory'}
$source=Split-Path $PSScriptRoot
New-Item -ItemType Directory -Force "$InstallDirectory\runner_console" | Out-Null
Copy-Item "$source\runner_console\*.py" "$InstallDirectory\runner_console" -Force
Copy-Item "$source\run.py" "$InstallDirectory\run.py" -Force
$config="$InstallDirectory\config.json"
[IO.File]::WriteAllText($config,(@{runner_dir=$RunnerDirectory;data_dir=$DataDirectory}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
$hookArgs=@("$InstallDirectory\run.py",'--config',$config,'install-hooks')
if($ReplaceHooks){$hookArgs+='--replace-hooks'}
& $PythonExe @hookArgs
if($LASTEXITCODE -ne 0){throw 'Could not install hooks; existing hooks require explicit -ReplaceHooks or manual integration.'}
if($GrantBatchLogonRight){
  $snapshot="$InstallDirectory\rights-before.inf"
  & secedit.exe /export /cfg $snapshot /areas USER_RIGHTS /quiet
  if($LASTEXITCODE -ne 0){throw 'Cannot export current logon rights'}
  $line=Get-Content $snapshot | Where-Object {$_ -match '^SeBatchLogonRight\s*='}
  $old=if($line){($line -split '=',2)[1].Trim()}else{''}
  $rights=@($old -split ','|Where-Object {$_})+@('*'+$sid)
  $text=@('[Unicode]','Unicode=yes','[Version]','signature="$CHICAGO$"','Revision=1','[Privilege Rights]',('SeBatchLogonRight = '+(($rights|Select-Object -Unique)-join ','))) -join [Environment]::NewLine
  $policy="$InstallDirectory\batch-right.inf"
  Set-Content $policy $text -Encoding Unicode
  & secedit.exe /configure /db "$InstallDirectory\batch-right.sdb" /cfg $policy /areas USER_RIGHTS /log "$InstallDirectory\batch-right.log" /quiet
  if($LASTEXITCODE -ne 0){throw 'Cannot grant batch-logon right'}
}
$action=New-ScheduledTaskAction -Execute $PythonExe -Argument ('"'+$InstallDirectory+'\run.py" --config "'+$config+'" collect') -WorkingDirectory $InstallDirectory
$settings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName ActionsRunnerConsoleCollector -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $settings -User $account -Password $Credential.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
Start-ScheduledTask ActionsRunnerConsoleCollector
if($StartAtLogon){
  $show=New-ScheduledTaskAction -Execute $PythonExe -Argument ('"'+$InstallDirectory+'\run.py" --config "'+$config+'" show') -WorkingDirectory $InstallDirectory
  $principal=New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName ActionsRunnerConsoleDisplay -Action $show -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $account) -Settings $settings -Principal $principal -Force | Out-Null
}
if($RestartRunner){$service=(Get-Content "$RunnerDirectory\.service").Trim();Restart-Service $service}else{Write-Host 'Restart the GitHub runner when idle to load the new hooks.'}
Write-Host "Installed. Sign in as $account to view the dashboard."
Write-Host 'If the collector cannot start, verify the account has Log on as a batch job; domain policy may override local grants.'
