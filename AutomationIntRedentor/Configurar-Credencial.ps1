param([string]$Usuario='copilot.microset')
$dest=Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'vpn.credential.xml'
$senha=Read-Host "Senha da VPN Redentor para $Usuario" -AsSecureString
[pscredential]::new($Usuario,$senha)|Export-Clixml -LiteralPath $dest -Force
Write-Host "Credencial criptografada para o usuário $env:USERNAME em $dest"

