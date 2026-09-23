param(
  [string]$MpcExe = 'C:\Unisys\Unisys - Copia\Clients\MPC\mpcapi32.exe',
  [string]$PastaCsv = 'C:\Unisys\Braso',
  [int]$TimeoutSegundos = 180,
  [switch]$ManterMpcAberto
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("execucao_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))

function Log([string]$mensagem) {
  $linha = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $mensagem
  Add-Content -LiteralPath $log -Value $linha -Encoding UTF8
  Write-Host $linha
}

function ArquivoMaisRecente([datetime]$desde) {
  Get-ChildItem -LiteralPath $PastaCsv -File -Filter 'Copilot_Linha*.Csv' |
    Where-Object { $_.LastWriteTime -ge $desde -and $_.Name -notmatch '_ultimos3dias\.csv$' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
}

function AguardarCsv([datetime]$desde) {
  $limite = (Get-Date).AddSeconds($TimeoutSegundos)
  do {
    $arquivo = ArquivoMaisRecente $desde
    if ($arquivo) {
      $tam1 = $arquivo.Length
      Start-Sleep -Seconds 2
      $arquivo.Refresh()
      if ($arquivo.Length -eq $tam1 -and $arquivo.Length -gt 0) { return $arquivo }
    }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $limite)
  return $null
}

function AbrirSessao([Diagnostics.Process]$processo, [string]$sessao) {
  Log "Tentando sessão '$sessao'."
  $shell = New-Object -ComObject WScript.Shell
  if (-not $shell.AppActivate($processo.Id)) { throw 'Não foi possível ativar a janela do MPC.' }
  Start-Sleep -Milliseconds 500
  # Menu File > Open Session. O MPC 4.3 é Win32 legado e não expõe UI Automation.
  $shell.SendKeys('%fo')
  Start-Sleep -Milliseconds 800
  $shell.SendKeys('^a')
  $shell.SendKeys($sessao)
  $shell.SendKeys('{ENTER}')
}

if (-not (Test-Path -LiteralPath $MpcExe)) { throw "Executável não encontrado: $MpcExe" }
if (-not (Test-Path -LiteralPath $PastaCsv)) { throw "Pasta dos CSVs não encontrada: $PastaCsv" }

$inicio = Get-Date
$processo = Start-Process -FilePath $MpcExe -WorkingDirectory (Split-Path -Parent $MpcExe) -PassThru
Log "MPC iniciado. PID=$($processo.Id)"
Start-Sleep -Seconds 2

$csv = $null
foreach ($sessao in @('ocopilot', 'ocopilot2')) {
  AbrirSessao $processo $sessao
  $csv = AguardarCsv $inicio
  if ($csv) { Log "CSV gerado pela sessão '$sessao': $($csv.FullName)"; break }
  Log "A sessão '$sessao' não gerou CSV em $TimeoutSegundos segundos. Tentando fallback."
  $shell = New-Object -ComObject WScript.Shell
  [void]$shell.AppActivate($processo.Id)
  $shell.SendKeys('{ESC}')
  Start-Sleep -Milliseconds 500
}

if (-not $csv) { throw 'Nenhuma das sessões gerou um Copilot_Linha*.Csv novo.' }

& (Join-Path $projectDir 'Tratar-CsvCopilot.ps1') -Arquivo $csv.FullName
if ($LASTEXITCODE -ne 0) { throw "O tratamento do CSV terminou com código $LASTEXITCODE." }

if (-not $ManterMpcAberto -and -not $processo.HasExited) {
  $processo.CloseMainWindow() | Out-Null
  Log 'Solicitado fechamento normal do MPC.'
}
Log 'Processo concluído com sucesso.'

