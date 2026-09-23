param(
  [Parameter(Mandatory=$true)][string]$Arquivo,
  [string]$Saida
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Arquivo)) { throw "CSV não encontrado: $Arquivo" }
if (-not $Saida) {
  $dir = Split-Path -Parent $Arquivo
  $base = [IO.Path]::GetFileNameWithoutExtension($Arquivo)
  $Saida = Join-Path $dir ($base + '_ultimos3dias.csv')
}

$pt = [Globalization.CultureInfo]::GetCultureInfo('pt-BR')
$linhas = @(Import-Csv -LiteralPath $Arquivo -Delimiter ';')
if (-not $linhas.Count) { throw 'O CSV está vazio.' }
$dataProp = $linhas[0].PSObject.Properties.Name | Where-Object { $_.Trim() -eq 'Data' } | Select-Object -First 1
if (-not $dataProp) { throw "A coluna 'Data' não foi encontrada." }

$validas = foreach ($linha in $linhas) {
  $data = [datetime]::MinValue
  $dataTexto = ([string]$linha.$dataProp).Trim()
  if (-not [datetime]::TryParseExact($dataTexto, 'dd/MM/yyyy', $pt, [Globalization.DateTimeStyles]::None, [ref]$data)) {
    throw "Data inválida no CSV: '$dataTexto'"
  }
  [pscustomobject]@{ DataParsed = $data.Date; Linha = $linha }
}

$dias = @($validas.DataParsed | Sort-Object -Unique -Descending)
if ($dias.Count -lt 3) { throw "O CSV contém somente $($dias.Count) dia(s) distinto(s); são necessários pelo menos 3." }
$tresDias = @($dias | Select-Object -First 3)
$ontem = (Get-Date).Date.AddDays(-1)
$temOntem = $dias -contains $ontem

$tratadas = @($validas | Where-Object { $tresDias -contains $_.DataParsed } | ForEach-Object { $_.Linha })
$tratadas | Export-Csv -LiteralPath $Saida -Delimiter ';' -NoTypeInformation -Encoding UTF8

$resumo = [ordered]@{
  arquivoOrigem = (Resolve-Path -LiteralPath $Arquivo).Path
  arquivoTratado = (Resolve-Path -LiteralPath $Saida).Path
  geradoEm = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  diasMantidos = @($tresDias | ForEach-Object { $_.ToString('dd/MM/yyyy') })
  linhasOrigem = $linhas.Count
  linhasTratadas = $tratadas.Count
  diaAnteriorEsperado = $ontem.ToString('dd/MM/yyyy')
  contemDiaAnterior = $temOntem
}
$resumoPath = [IO.Path]::ChangeExtension($Saida, '.validacao.json')
$resumo | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $resumoPath -Encoding UTF8

Write-Host "Arquivo tratado: $Saida"
Write-Host "Dias mantidos: $($resumo.diasMantidos -join ', ')"
if (-not $temOntem) {
  Write-Error "O CSV não contém o dia anterior ($($resumo.diaAnteriorEsperado))."
  exit 2
}
Write-Host "Validação OK: contém o dia anterior ($($resumo.diaAnteriorEsperado))."
exit 0
