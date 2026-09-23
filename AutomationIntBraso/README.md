# Automação MPC Copilot

Abre o MPC 4.3, executa `File > Open Session`, tenta `ocopilot` e usa `ocopilot2`
como fallback quando nenhum CSV novo é gerado. Depois localiza o novo
`Copilot_Linha*.Csv` em `C:\Unisys\Braso` e cria:

- `*_ultimos3dias.csv`: somente os três dias mais recentes presentes no arquivo;
- `*_ultimos3dias.validacao.json`: datas mantidas, contagens e validação de ontem.

O CSV original é preservado.

## Executar

Dê duplo clique em `Executar.bat` ou rode:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Automacao-MpcCopilot.ps1
```

O Windows precisa estar com uma sessão de usuário desbloqueada, porque o MPC é
uma aplicação gráfica antiga e recebe a seleção da sessão por teclado.

## Agendar

No Agendador de Tarefas, use `Executar.bat` e marque **Executar somente quando o
usuário estiver conectado**. Essa opção é necessária para a janela do MPC.

## Códigos de erro

- `0`: CSV criado e contém o dia anterior;
- `2`: o arquivo tratado foi criado, mas o CSV de origem não contém ontem;
- outros: MPC, arquivo ou formato inválido. Consulte a pasta `logs`.
