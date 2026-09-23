# Handoff — Integração SGTweb/Transnet → ACE (copiloto)

_Atualizado em 21/09/2026._

Pipeline que **extrai** os relatórios de **Abastecimento por Veículo** e **Viagens Realizadas por Funcionário** do SGTweb/Transnet (via HTTP puro, sem navegador) e **integra** no backend ACE/copiloto (via mutations GraphQL), replicando o `integracao-ace.component.ts` do frontend.

Cobre **4 empresas** em **2 instâncias** do SGT:

| Instância SGT | Empresa | cod SGT | sEmpresaId (ACE) | Setor abast (garagem) |
|---|---|---|---|---|
| `grupopontecoberta` | Ponte Coberta | 001 | **924** | Mesquita (`1`) |
| `grupopontecoberta` | N.S. Glória | 002 | **926** | Mesquita (`1`) |
| `pendotiba` | Pendotiba | 001 | **863** | Garagem Pendotiba (`21`) |
| `pendotiba` | Araçatuba | 004 | **914** | Garagem Araçatuba (`42`) |

---

## 1. Arquivos

| Arquivo | Papel |
|---|---|
| `extrair_relatorios_sgt.py` | **Engine**: login SGT, download dos relatórios (CSV nativo), parsing, e as mutations GraphQL de integração. Config no topo. |
| `agendador_sgt.py` | **Entry-point do cron**: calcula a janela de reprocesso, restringe a instância/empresa e dispara o engine em modo real. |
| `HANDOFF_SGT_ACE.md` | Este documento. |

Dependências: **Python 3** + pacote **`requests`** (`pip install requests`). Sem navegador.

---

## 2. Fluxo ponta a ponta

```
SGTweb/Transnet (HTTP)                     ACE / copiloto (GraphQL)
────────────────────                       ────────────────────────
login (base64+md5)
  └─ verPesquisar (form)                    login(login,pwc) → token dinâmico (muda por dia)
  └─ pesquisar (POST filtros)
  └─ verRelatorio → CSV (ISO-8859-1)
        │
        ├─ ABASTECIMENTO ─ registros_abast_from_csv ─┐
        │                                            ├─► apagaDia + grava + log (ver §4)
        └─ VIAGENS ─ registros_viagens_from_csv ─────┘
```

### Extração SGT (por empresa/relatório)
1. `GET  ...&m=verPesquisar` → baixa o formulário e lê os campos ocultos.
2. Preenche filtros: empresa (X2=selecionada, X1=demais), setor da garagem (abast), datas.
   - **Separador multi-seleção**: `«¦|¦»` (bytes `AB A6 7C A6 BB`). Tem que preencher **os dois lados** (X1 não-selecionadas e X2 selecionadas), senão o SGT ignora o filtro e traz todas.
   - Header **`Accept-Encoding: identity`** obrigatório (senão o download trunca ~29 KB).
3. `POST ...&m=pesquisar` → 302 → `GET ...&m=verRelatorio` → **CSV** (`application/csv`, ISO-8859-1).

> Se o `verRelatorio` devolver HTML (a própria tela de busca) em vez de CSV, é **falha do lado do SGT** para aquele relatório/instância (já aconteceu com o abast do pendotiba em 26/08). Não é corrigível pelo cliente; normaliza sozinho depois.

---

## 3. Rotas GraphQL (endpoint único)

**`POST https://wws.copiloto.com.br/node`** — corpo `{"query": "..."}`. O `token` vai **como argumento** em cada mutation (não em header).

| Operação | Tipo | Uso |
|---|---|---|
| `login(login, pwc, emailTkn:"", matricula:"", codEmpresa:-1)` | query | 1×/execução. `pwc` já vem AES (usar verbatim). Retorna `token userId nivel errCode errMsg`. |
| `apagaDiaIntAceAbast(token, sEmpresaId, dia)` | mutation | abast: limpa o dia |
| `gravaIntAceAbast(token, sEmpresaId, registro)` | mutation | abast: 1 por registro |
| `apagaDiaIntAceMot(token, sEmpresaId, dia)` | mutation | motorista: limpa o dia |
| `gravaIntAceMot(token, sEmpresaId, registro)` | mutation | motorista: 1 por turno |
| `gravaLogProcessamento(token, sEmpresaId, tp_resumo, dia, stsproc, sUsuarioId, qtde, origem)` | mutation | log por dia (se 0 erros) |

**Parâmetros do log (`gravaLogProcessamento`):**

| | tp_resumo | **stsproc** | origem |
|---|---|---|---|
| Abastecimento | `0` | **`7`** (fixo) | `"integracao_ace"` |
| Motorista | `1` | **`3`** (padrão desde 21/09/2026) | `"integracao_ace"` |

### Shapes dos registros
```graphql
# gravaIntAceAbast.registro
{ dia, nr_carro, hodo_ini, hodo_fim, km, kml, diesel,
  chassi, motor, valorabast }          # turno NÃO é enviado (IntAceAbastInput rejeita)

# gravaIntAceMot.registro
{ dia, nr_carro, matricula, linha, hr_pegada, hr_largada, diesel:null }
```

### Em standby (previsto, NÃO usado)
- **`gravaIntACEMotV2`** (motorista com roleta) — comentada no backend; usamos `gravaIntAceMot` (V1).
- Dados **roleta** (motorista) e **turno** (abast) são capturados no parser mas **não enviados** — aguardam a rota/campo no backend. Flags: `ENVIAR_TURNO_ABAST=False`.

---

## 4. Pipeline de integração (por empresa/relatório) — SEGURO

Mesma sequência para abast e motorista:

1. **Pré-validação**: grava **1 registro ANTES de apagar**. Se o backend rejeitar o shape, **aborta sem ter apagado nada**.
2. **apagaDia**: `apagaDia*` **1× por dia** do período (sequencial). Se falhar, aborta antes de gravar.
3. **grava**: `grava*` 1 por registro/turno, com **concorrência 3** (`ThreadPoolExecutor`).
4. **log**: `gravaLogProcessamento` 1× por dia, **somente se 0 erros**.

> Consequência prática: se o **download** do relatório falhar, aquela empresa é **pulada sem apagar nada** (a falha ocorre antes do apagaDia). Nunca deixa o dia apagado sem reinserir.

Retry: conexão/DNS e 5xx com backoff; **`read_retry=0` nas mutations** (evita INSERT duplicado se a resposta der timeout depois do INSERT ter chegado).

### Regras de dados
- **Linhas-ponte** (descontinuidade de hodômetro: km=0 E diesel=0 E não é continuação) são **descartadas SÓ** para `EMPRESAS_FILTRAR_PONTE = {924, 926}` (Ponte/Glória), p/ bater com o `intaceabast`. Pendotiba/Araçatuba sobem tudo (base delas está duplicada, não serve de alvo).
- **Continuações**: 2º+ abastecimento do mesmo veículo/dia (vêm sem repetir a data) são captadas.
- **Motorista** é agrupado em **turnos** (1ª pegada → última largada, por mudança de linha/veículo) — port do `processMotHierarchical`.
- `nr_carro` do motorista vai **sem ponto** (ex.: `190095`, não `190.095`) p/ casar com o abast.
- Placa: a `gravaIntAceMot` cria o veículo no backend se o `nr_carro` não existir em `s_veiculos` (origem do prefixo "A" em placas — comportamento do backend, não do script).

---

## 5. Config do engine (`extrair_relatorios_sgt.py`)

| Chave | Valor atual | Observação |
|---|---|---|
| `ENVIAR_CHASSI_MOTOR_VALOR` | `True` | envia chassi/motor/valorabast no abast |
| `ENVIAR_TURNO_ABAST` | `False` | `turno` não existe no `IntAceAbastInput` |
| `EMPRESAS_FILTRAR_PONTE` | `{924, 926}` | filtra linha-ponte só Ponte/Glória |
| `INTEGRACAO["graphql_url"]` | `https://wws.copiloto.com.br/node` | endpoint único |
| `INTEGRACAO["login_user"]` | `monitoramento` | |
| `INTEGRACAO["login_pwc"]` | `U2FsdGVkX1+...` (AES) | usar verbatim |
| `INTEGRACAO["concorrencia"]` | `3` (via agendador) | gentil com o backend |

`RELATORIOS = ["abastecimento", "viagens"]`.

### 5.1 Credenciais por variável de ambiente

As credenciais são lidas de **env vars**, com **fallback para os valores atuais** (roda igual sem configurar nada; em produção você pode sobrescrever/remover os fallbacks):

| Env var | O que é | Fallback (atual) |
|---|---|---|
| `SGT_GPC_USER` | usuário SGT grupopontecoberta | `copilot` |
| `SGT_GPC_PASS` | senha SGT grupopontecoberta | `abc*123` |
| `SGT_PEN_USER` | usuário SGT pendotiba | `copilot` |
| `SGT_PEN_PASS` | senha SGT pendotiba | `123456` |
| `ACE_LOGIN_USER` | usuário GraphQL copiloto | `monitoramento` |
| `ACE_LOGIN_PWC` | pwc AES do GraphQL (verbatim) | `U2FsdGVkX1+...` |

Definir no servidor (ex.: em `/etc/sgt.env`, carregado pelo cron — ver §7):
```bash
export SGT_GPC_USER=copilot
export SGT_GPC_PASS='abc*123'
export SGT_PEN_USER=copilot
export SGT_PEN_PASS='123456'
export ACE_LOGIN_USER=monitoramento
export ACE_LOGIN_PWC='U2FsdGVkX1+nNqK/6auUDI079nDGuqpl8XwcGd4ENj0='
```
> Para tirar 100% os segredos do código, defina as 6 env vars e apague os fallbacks nos `os.environ.get(...)` do engine. Enquanto os fallbacks existirem, o processo roda idêntico ao ambiente atual mesmo sem env.

---

## 6. Agendador (`agendador_sgt.py`)

```
python3 agendador_sgt.py <instancia> [empresa|all] [tipoProc]
```
- `instancia`: `grupopontecoberta` | `pendotiba`
- `empresa` (opcional): `001` / `002` / `004`; `all` ou omitido = todas da instância
- `tipoProc` (opcional): `1`=ReIntegrar (padrão) | `2`=ReProcessar

**Janela de reprocesso** (calculada automaticamente, termina SEMPRE em **ontem** — o dia atual não entra):
- **Segunda-feira** → 7 dias (`hoje-7 .. hoje-1`)
- **Demais dias** → 3 dias (`hoje-3 .. hoje-1`)

Saída (CSV/JSON/payloads): env **`SGT_SAIDA`** ou `<dir do script>/saida`.
Liga automaticamente: `INTEGRACAO` real, abast + viagens, concorrência 3.

---

## 7. Cron do Linux — agendamento por grupo

Regras definidas:
- **Ponte Coberta + N.S. Glória** (`grupopontecoberta`): **todo dia às 16h, EXCETO domingo**.
- **Pendotiba + Araçatuba** (`pendotiba`): **todo dia às 8h e 12h**.

> **Fuso**: o cron usa o fuso do servidor. Garanta `America/Sao_Paulo` (`timedatectl set-timezone America/Sao_Paulo`) senão os horários saem trocados.

### 7.1 Recomendado — 1 comando por grupo (todas as empresas do grupo em sequência)

```cron
# ===== SGT -> ACE  (ajuste /opt/sgt e o caminho do python3) =====
# Ponte Coberta + N.S. Gloria — todo dia as 16h, EXCETO domingo (1-6 = seg..sab)
0 16 * * 1-6  cd /opt/sgt && /usr/bin/python3 agendador_sgt.py grupopontecoberta all >> /opt/sgt/logs/grupopontecoberta.log 2>&1

# Pendotiba + Aracatuba — todo dia as 8h e 12h
0 8,12 * * *  cd /opt/sgt && /usr/bin/python3 agendador_sgt.py pendotiba all >> /opt/sgt/logs/pendotiba.log 2>&1
```

A janela (7 dias na segunda, 3 nos demais) é resolvida **sozinha** pelo agendador — não precisa de linhas separadas por dia.

### 7.2 Alternativa — segmentado por empresa (logs separados, escalonado p/ não abrir 2 sessões SGT juntas)

```cron
# grupopontecoberta — 16h (seg..sab), Ponte e Gloria com 5 min de diferenca
0  16 * * 1-6  cd /opt/sgt && /usr/bin/python3 agendador_sgt.py grupopontecoberta 001 >> /opt/sgt/logs/ponte_coberta.log 2>&1
5  16 * * 1-6  cd /opt/sgt && /usr/bin/python3 agendador_sgt.py grupopontecoberta 002 >> /opt/sgt/logs/ns_gloria.log 2>&1

# pendotiba — 8h e 12h, Pendotiba e Aracatuba com 5 min de diferenca
0  8,12 * * *  cd /opt/sgt && /usr/bin/python3 agendador_sgt.py pendotiba 001 >> /opt/sgt/logs/pendotiba.log 2>&1
5  8,12 * * *  cd /opt/sgt && /usr/bin/python3 agendador_sgt.py pendotiba 004 >> /opt/sgt/logs/aracatuba.log 2>&1
```

### 7.3 Instalação
```bash
sudo mkdir -p /opt/sgt/logs
# extraia o pacote (zip) em /opt/sgt  -> extrair_relatorios_sgt.py, agendador_sgt.py, etc.
cd /opt/sgt
pip3 install -r requirements.txt          # (só 'requests')
timedatectl set-timezone America/Sao_Paulo

# (opcional) credenciais por env var — senão usa os fallbacks embutidos:
sudo cp .env.example /etc/sgt.env         # edite os valores
crontab -e                                # cole as linhas abaixo
crontab -l
```

Se usar `/etc/sgt.env`, faça o cron carregá-lo (prefixe o comando):
```cron
0 16 * * 1-6  set -a; . /etc/sgt.env; set +a; cd /opt/sgt && /usr/bin/python3 agendador_sgt.py grupopontecoberta all >> /opt/sgt/logs/grupopontecoberta.log 2>&1
0 8,12 * * *  set -a; . /etc/sgt.env; set +a; cd /opt/sgt && /usr/bin/python3 agendador_sgt.py pendotiba all >> /opt/sgt/logs/pendotiba.log 2>&1
```
Sem `/etc/sgt.env`, use as linhas do §7.1 direto (rodam com os fallbacks).

Rodar manualmente (fora do cron), para um período específico, use o engine direto:
```bash
python3 extrair_relatorios_sgt.py 14/09/2026 20/09/2026    # (com INTEGRACAO ligada no código)
```

---

## 8. Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `verRelatorio` devolve HTML (~315 KB) e não CSV | Relatório fora **no SGT** (server-side) | Reexecutar depois; não é do script (ponte/viagens seguem OK) |
| `LOGIN FALHOU: Read timed out` numa instância | Timeout transitório do SGT | Reexecutar só aquela instância; o cron pega na próxima janela |
| `viagens ... ConnectionReset/timeout` (Ponte/Glória) | Relatório de viagem de 7+ dias sobrecarrega o SGT | Reprocessar só viagens daquele grupo, ou em blocos menores |
| `ABORTADA na validação de shape` | Backend rejeitou um campo novo | **Nada foi apagado**; ajustar shape (ex.: `ENVIAR_TURNO_ABAST`) |
| Empresa com menos dias de abast que o esperado | Lançamento faltando no SGT (garagem) | Conferir com a garagem (recorrente em Araçatuba) |

---

## 9. Conteúdo do pacote (zip)

```
sgt_ace_deploy/
├─ extrair_relatorios_sgt.py   # engine (idêntico ao que roda hoje)
├─ agendador_sgt.py            # entry-point do cron
├─ requirements.txt            # requests
├─ .env.example               # as 6 env vars (valores atuais)
├─ crontab.example            # linhas de cron dos §7.1/§7.3
├─ HANDOFF_SGT_ACE.md         # este documento
└─ logs/                       # (criada em runtime)
```
Roda **out-of-the-box** (fallbacks = credenciais atuais). Só precisa de Python 3 + `requests`.

## 10. Log de decisões
- **21/09/2026**: credenciais parametrizadas por **env var** (com fallback aos valores atuais) — `SGT_GPC_USER/PASS`, `SGT_PEN_USER/PASS`, `ACE_LOGIN_USER/PWC`.
- **21/09/2026**: log do **motorista** passa a usar **`stsproc:3` permanente** (antes 7). Abast permanece `stsproc:7`. Editado em `integrar_viagens` (var `stsproc = 3`, chamada real passa `stsproc`) e no default de `_mut_log_mot`.
- **26/08/2026**: `turno` desligado no abast (`ENVIAR_TURNO_ABAST=False`) — `IntAceAbastInput` rejeita.
- Janela do agendador ajustada para terminar **em ontem** (o dia atual não entra).
- **22/09/2026**: integração passa a rodar **DIA A DIA em ordem crescente** (abast e motorista): para cada dia `apagaDia` → `grava*` do dia (sequencial) → `gravaLogProcessamento` do dia (só se o dia teve 0 erro). Antes era em bloco: apagava todos os dias, gravava tudo em paralelo (3 threads) e logava no fim, com os dias na ordem de aparição do CSV (ex.: 19, 21, 20). Se um `apagaDia` falhar, para ali e os dias seguintes não são tocados. O registro de teste de formato agora é do primeiro dia. `INTEGRACAO["concorrencia"]` deixou de ser usado.
