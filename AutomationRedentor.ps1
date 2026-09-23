param(
  [int]$TempoVpnSegundos = 60,
  [switch]$ValidarSomente,
  [switch]$ManterAplicativosAbertos,
  [switch]$SolicitarCredencial
)

$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$credPath = Join-Path $dir 'vpn.credential.xml'
$logDir = Join-Path $dir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("execucao_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))

function Log([string]$m) { $l="{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$m; Add-Content $log $l -Encoding UTF8; Write-Host $l }

Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public static class Win32Redentor {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
  [StructLayout(LayoutKind.Sequential)] public struct SYSTEMTIME { public ushort Year,Month,DayOfWeek,Day,Hour,Minute,Second,Milliseconds; }
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p,IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h,EnumProc p,IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h,out int p);
  [DllImport("user32.dll",CharSet=CharSet.Auto)] public static extern int GetWindowText(IntPtr h,StringBuilder b,int n);
  [DllImport("user32.dll",CharSet=CharSet.Auto)] public static extern int GetClassName(IntPtr h,StringBuilder b,int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h,uint m,IntPtr w,ref SYSTEMTIME l);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,UIntPtr e);
}
'@
Add-Type -AssemblyName UIAutomationClient

function Texto-Janela([IntPtr]$h) { $b=New-Object Text.StringBuilder 512; [void][Win32Redentor]::GetWindowText($h,$b,512); $b.ToString() }
function Classe-Janela([IntPtr]$h) { $b=New-Object Text.StringBuilder 256; [void][Win32Redentor]::GetClassName($h,$b,256); $b.ToString() }
function Filhos([IntPtr]$h) { $a=New-Object Collections.ArrayList; [Win32Redentor]::EnumChildWindows($h,{param($x,$l);[void]$a.Add($x);$true},[IntPtr]::Zero)|Out-Null; @($a) }
function Esperar-Janela([int]$processId,[string]$titulo,[int]$seg=30) {
  $fim=(Get-Date).AddSeconds($seg)
  do { $achado=[IntPtr]::Zero; [Win32Redentor]::EnumWindows({param($h,$l);$p=0;[void][Win32Redentor]::GetWindowThreadProcessId($h,[ref]$p);if($p -eq $processId -and (Texto-Janela $h) -like "*$titulo*"){$script:achado=$h;$false}else{$true}},[IntPtr]::Zero)|Out-Null; if($script:achado -ne [IntPtr]::Zero){$r=$script:achado;$script:achado=[IntPtr]::Zero;return $r}; Start-Sleep -Milliseconds 300 } while((Get-Date)-lt $fim)
  throw "Janela '$titulo' não apareceu em $seg segundos."
}
function Clicar([IntPtr]$h) { [void][Win32Redentor]::PostMessage($h,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero) }
function Definir-Data($elemento,[datetime]$d,$shell) {
  $r=$elemento.Current.BoundingRectangle
  [void][Win32Redentor]::SetCursorPos([int]($r.Left+12),[int]($r.Top+$r.Height/2))
  [Win32Redentor]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [Win32Redentor]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 150
  $shell.SendKeys($d.ToString('dd')); $shell.SendKeys('{RIGHT}')
  $shell.SendKeys($d.ToString('MM')); $shell.SendKeys('{RIGHT}')
  $shell.SendKeys($d.ToString('yyyy')); $shell.SendKeys('{TAB}')
  Start-Sleep -Milliseconds 150
}
function Clicar-Sim([int]$processId,[int]$seg=30) {
  Start-Sleep -Seconds 1
  $s=New-Object -ComObject WScript.Shell
  if(-not $s.AppActivate($processId)){throw 'Não foi possível ativar o modal do CopilotQualify.'}
  $s.SendKeys('%s')
  Start-Sleep -Milliseconds 700
}
function Esperar-TextoCopilot($auto,[string]$texto,[int]$seg=120) {
  $fim=(Get-Date).AddSeconds($seg)
  do {
    $elementos=$auto.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
    foreach($elemento in $elementos) {
      $nome=[string]$elemento.Current.Name
      $valor=''
      try { $valor=[string]$elemento.GetCurrentPropertyValue([Windows.Automation.ValuePattern]::ValueProperty) } catch {}
      if($nome -like "*$texto*" -or $valor -like "*$texto*") { return $true }
    }
    Start-Sleep -Seconds 1
  } while((Get-Date)-lt $fim)
  return $false
}
function Clique-Relativo([IntPtr]$h,[double]$fx,[double]$fy) { $r=New-Object Win32Redentor+RECT;[void][Win32Redentor]::GetWindowRect($h,[ref]$r);$x=[int]($r.L+($r.R-$r.L)*$fx);$y=[int]($r.T+($r.B-$r.T)*$fy);[void][Win32Redentor]::SetCursorPos($x,$y);[Win32Redentor]::mouse_event(2,0,0,0,[UIntPtr]::Zero);[Win32Redentor]::mouse_event(4,0,0,0,[UIntPtr]::Zero) }
function Clicar-Cliente([IntPtr]$h,[int]$x,[int]$y) {
  $lp=[IntPtr](($y -shl 16) -bor ($x -band 0xffff))
  [void][Win32Redentor]::SendMessage($h,0x0201,[IntPtr]1,$lp)
  [void][Win32Redentor]::SendMessage($h,0x0202,[IntPtr]::Zero,$lp)
}
function Testar-VpnRedentor {
  # Nao depender do idioma do ipconfig: a descricao do adaptador e estavel.
  $adaptadores=Get-CimInstance Win32_NetworkAdapterConfiguration -ErrorAction SilentlyContinue |
    Where-Object { $_.Description -like '*Fortinet SSL VPN Virtual Ethernet Adapter*' -and $_.IPEnabled }
  foreach($adaptador in $adaptadores) {
    if(@($adaptador.IPAddress) | Where-Object { $_ -and $_ -notlike '169.254.*' -and $_ -notlike 'fe80:*' }) { return $true }
  }
  return $false
}
function Confirmar-CertificadoForti([int]$seg=25) {
  $fim=(Get-Date).AddSeconds($seg); $dialogo=[IntPtr]::Zero; $script:certDialog=[IntPtr]::Zero
  do {
    [Win32Redentor]::EnumWindows({param($h,$l);if((Texto-Janela $h)-eq 'Server Certificate Warning'){$script:certDialog=$h;$false}else{$true}},[IntPtr]::Zero)|Out-Null
    if($script:certDialog -ne [IntPtr]::Zero){$dialogo=$script:certDialog;break}
    Start-Sleep -Milliseconds 300
  } while((Get-Date)-lt $fim)
  $script:certDialog=[IntPtr]::Zero
  if($dialogo -eq [IntPtr]::Zero){return $false}
  $sim=Filhos $dialogo | Where-Object {(Texto-Janela $_)-eq 'Sim' -and (Classe-Janela $_)-eq 'Button'} | Select-Object -First 1
  if(-not $sim){throw "Botão 'Sim' do aviso de certificado não encontrado."}
  [void][Win32Redentor]::PostMessage([IntPtr]$sim,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero)
  Log 'Aviso de certificado do FortiClient confirmado.'
  return $true
}

if($SolicitarCredencial) {
  $vpnUsuario=Read-Host 'Usuario da VPN Redentor'
  $vpnSenha=Read-Host 'Senha da VPN Redentor' -AsSecureString
  $cred=[pscredential]::new($vpnUsuario,$vpnSenha)
} else {
  if(-not(Test-Path $credPath)){throw "Credencial ausente. Execute Configurar-Credencial.ps1 primeiro."}
  try {
    $cred=Import-Clixml -LiteralPath $credPath
  } catch {
    throw "Nao foi possivel descriptografar vpn.credential.xml. Execute Configurar-Credencial.ps1 novamente com o mesmo usuario do Windows que executara esta automacao. Detalhe: $($_.Exception.Message)"
  }
}
if(-not $cred -or -not $cred.UserName -or -not $cred.Password){throw 'A credencial da VPN esta vazia ou invalida. Execute Configurar-Credencial.ps1 novamente.'}
$hoje=(Get-Date).Date; $fim=$hoje.AddDays(-1); $inicio=if($hoje.DayOfWeek -eq 'Monday'){$hoje.AddDays(-7)}else{$hoje.AddDays(-3)}
Log "Período calculado: $($inicio.ToString('dd/MM/yyyy')) a $($fim.ToString('dd/MM/yyyy'))."

$exe=(Get-ChildItem "$env:LOCALAPPDATA\Apps\2.0" -Filter CopilotQualify.exe -File -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
if(-not $exe){throw 'CopilotQualify instalado não foi encontrado no cache ClickOnce.'}
[void](Start-Process $exe -WorkingDirectory (Split-Path $exe) -PassThru)
$limiteCop=(Get-Date).AddSeconds(30); $cop=$null
do { $cop=Get-Process CopilotQualify -ErrorAction SilentlyContinue|Where-Object{$_.MainWindowTitle -like '*Copilot Qualify*'}|Sort-Object StartTime -Descending|Select-Object -First 1; if(-not $cop){Start-Sleep -Milliseconds 300} }while(-not $cop -and (Get-Date)-lt $limiteCop)
if(-not $cop){throw 'Janela do CopilotQualify não apareceu em 30 segundos.'}
$janela=$cop.MainWindowHandle
$cond=New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::ProcessIdProperty,$cop.Id)
$auto=[Windows.Automation.AutomationElement]::RootElement.FindFirst([Windows.Automation.TreeScope]::Children,$cond)
if(-not $auto){throw 'A árvore de automação do CopilotQualify não ficou disponível.'}
$elementos=$auto.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
$datas=@($elementos|Where-Object{$_.Current.ClassName -like '*SysDateTimePick32*'}|Sort-Object{$_.Current.BoundingRectangle.Top})
if($datas.Count -ne 2){throw "Esperados 2 seletores de data; encontrados $($datas.Count)."}
$shell=New-Object -ComObject WScript.Shell; [void]$shell.AppActivate($cop.Id)
[void]$shell.AppActivate($cop.Id); Definir-Data $datas[0] $inicio $shell
[void]$shell.AppActivate($cop.Id); Definir-Data $datas[1] $fim $shell
$tentativaData=0
do {
  $elementos=$auto.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
  $datas=@($elementos|Where-Object{$_.Current.ClassName -like '*SysDateTimePick32*'}|Sort-Object{$_.Current.BoundingRectangle.Top})
  $datasLidas=@($datas|ForEach-Object{$_.Current.Name})
  if($datasLidas[0] -ne $inicio.ToString('dd/MM/yyyy')){[void]$shell.AppActivate($cop.Id); Definir-Data $datas[0] $inicio $shell}
  if($datasLidas[1] -ne $fim.ToString('dd/MM/yyyy')){[void]$shell.AppActivate($cop.Id); Definir-Data $datas[1] $fim $shell}
  $tentativaData++; Start-Sleep -Milliseconds 250
} while(($datasLidas[0] -ne $inicio.ToString('dd/MM/yyyy') -or $datasLidas[1] -ne $fim.ToString('dd/MM/yyyy')) -and $tentativaData -lt 3)
$elementos=$auto.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
$datasLidas=@($elementos|Where-Object{$_.Current.ClassName -like '*SysDateTimePick32*'}|Sort-Object{$_.Current.BoundingRectangle.Top}|ForEach-Object{$_.Current.Name})
if($datasLidas[0] -ne $inicio.ToString('dd/MM/yyyy') -or $datasLidas[1] -ne $fim.ToString('dd/MM/yyyy')){throw "Falha ao preencher datas: $($datasLidas -join ' / ')."}
$linuxEl=$elementos|Where-Object{$_.Current.Name -eq 'Processar Linux'}|Select-Object -First 1
$linux=if($linuxEl){[IntPtr]$linuxEl.Current.NativeWindowHandle}else{[IntPtr]::Zero}
if(-not $linux){throw "Flag 'Processar Linux' não encontrado."}
if([Win32Redentor]::SendMessage($linux,0x00F0,[IntPtr]::Zero,[IntPtr]::Zero).ToInt32()-eq 0){Clicar $linux}
$redentorEl=$elementos|Where-Object{$_.Current.Name -eq 'Redentor'}|Select-Object -First 1
$redentor=if($redentorEl){[IntPtr]$redentorEl.Current.NativeWindowHandle}else{[IntPtr]::Zero}
if(-not $redentor){throw "Botão 'Redentor' não encontrado."}
if($ValidarSomente){Log "Validação concluída: datas preenchidas, Processar Linux marcado e botão Redentor localizado. Nenhum processamento foi iniciado.";return}
Clicar $redentor; Clicar-Sim $cop.Id 30; Log 'Primeiro modal confirmado.'

if(-not (Esperar-TextoCopilot $auto 'Conectou SQL Server' 120)){
  throw "O log do CopilotQualify nao registrou 'Conectou SQL Server' em 120 segundos. A conexao VPN nao foi iniciada."
}
Log 'Log confirmado: Conectou SQL Server.'

if(-not (Testar-VpnRedentor)) {
  $fortiExe='C:\Program Files\Fortinet\FortiClient\FortiClientConsole.exe'
  if(-not (Test-Path $fortiExe)){throw "FortiClient nao encontrado em '$fortiExe'."}
  [void](Start-Process $fortiExe -PassThru)
  $limiteForti=(Get-Date).AddSeconds(20); $forti=$null
  do {$forti=Get-Process FortiClient -ErrorAction SilentlyContinue|Where-Object{$_.MainWindowTitle -like 'FortiClient - Zero Trust*'}|Select-Object -First 1;if(-not $forti){Start-Sleep -Milliseconds 300}}while(-not $forti -and (Get-Date)-lt $limiteForti)
  if(-not $forti){throw 'Janela funcional do FortiClient não apareceu.'}
  $fh=$forti.MainWindowHandle; [void][Win32Redentor]::SetForegroundWindow($fh); Start-Sleep -Milliseconds 500
  Clicar-Cliente $fh 468 424
  $shell.SendKeys('^a'); $shell.SendKeys($cred.UserName); $shell.SendKeys('{TAB}')
  $shell.SendKeys($cred.GetNetworkCredential().Password); $shell.SendKeys('{TAB}{ENTER}')
  Log 'Conexão VPN solicitada.'
  [void](Confirmar-CertificadoForti 25)
}

$limite=(Get-Date).AddSeconds($TempoVpnSegundos); $vpnOk=$false
do { $vpnOk=Testar-VpnRedentor; if(-not $vpnOk){Start-Sleep -Seconds 2} }while(-not $vpnOk -and (Get-Date)-lt $limite)
if(-not $vpnOk){throw "A VPN Redentor não ficou conectada em $TempoVpnSegundos segundos."}
Log 'VPN Redentor conectada.'; Start-Sleep -Seconds 3
Clicar-Sim $cop.Id 60; Log 'Segundo modal confirmado. Processamento Redentor liberado.'

if(-not $ManterAplicativosAbertos){Log 'Aplicativos mantidos durante o processamento; o CopilotQualify controla a conclusão.'}
