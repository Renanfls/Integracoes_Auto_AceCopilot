param(
  [string]$PastaDestino = 'C:\AutomationRedentor'
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PastaDestino 'AutomationRedentor.ps1'
if(-not (Test-Path $scriptPath)) {
  throw "AutomationRedentor.ps1 nao encontrado em $PastaDestino. Copie o projeto para essa pasta antes de instalar."
}

$taskName = 'AutomationRedentor - CopilotQualify'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$dias = @('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
$trigger08 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dias -At '08:00'
$trigger17 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dias -At '17:00'
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger08,$trigger17) -Principal $principal -Description 'Processa Redentor: 3 dias anteriores de terça a domingo e 7 dias anteriores às segundas.' -Force | Out-Null
Write-Host "Tarefa instalada: $taskName"
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
