# AutomationRedentor

Automatiza CopilotQualify e VPN FortiClient para o processamento da Redentor.

Período automático:

- terça a domingo: início em hoje − 3 e fim em hoje − 1;
- segunda-feira: início em hoje − 7 e fim em hoje − 1.

## Primeira execução

Execute `Configurar-Credencial.ps1` e informe a senha da VPN. Ela será guardada
com DPAPI no arquivo `vpn.credential.xml`, legível somente pelo mesmo usuário do
Windows na mesma máquina.

Depois execute `Executar.bat` com o Windows desbloqueado. A automação marca
`Processar Linux`, clica em `Redentor`, confirma o primeiro modal, conecta a VPN
`Redentor`, espera a interface Fortinet ficar ativa e confirma o segundo modal.

Os registros ficam em `logs`.

Para testar somente a abertura e o preenchimento do CopilotQualify, use:

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\AutomationRedentor.ps1 -ValidarSomente`

A credencial DPAPI precisa ser criada e usada pelo mesmo usuario do Windows,
na mesma maquina. Se aparecer erro de descriptografia, execute novamente
`Configurar-Credencial.ps1` no usuario que executara `Executar.bat`.
