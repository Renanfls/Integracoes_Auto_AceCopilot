$ErrorActionPreference = 'Stop'

$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
if($cap.State -ne 'Installed') {
  Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Host
}

Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

if(-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}

if(-not (Get-LocalUser -Name 'Jvcosta' -ErrorAction SilentlyContinue)) {
  throw "Usuario local Jvcosta nao foi encontrado nesta maquina."
}

Write-Host 'SSH habilitado com sucesso.'
Get-Service sshd | Select-Object Name,Status,StartType
Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' | Select-Object DisplayName,Enabled,Direction,Action
