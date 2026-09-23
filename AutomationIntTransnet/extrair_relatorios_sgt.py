# -*- coding: utf-8 -*-
"""
Extrator automático de relatórios do SGTweb / Transnet  (multi-instância)
Relatórios:
  • Abastecimento por Veículo            (frota.abastecimento.CRelatorioAbastecimentoVeiculo)
  • Viagens Realizadas por Funcionário   (trafego.CRelatorioViagemRealizadaFuncionario)

Instâncias / empresas cobertas:
  grupopontecoberta -> 001 Ponte Coberta, 002 N. S. Glória   (setor abast: Mesquita)
  pendotiba         -> 001 Pendotiba,     004 Araçatuba      (setor abast: garagem própria)

Para cada empresa gera, por relatório: CSV (export nativo) + JSON (estruturado).
Abastecimento é filtrado pelo SETOR DA GARAGEM de cada empresa (igual à extração manual).
Viagens traz todos os setores funcionais.

Uso:
    python extrair_relatorios_sgt.py                       # período rolante padrão
    python extrair_relatorios_sgt.py 09/08/2026 11/08/2026 # período fixo

Requisitos: pip install requests   (sem navegador)

Observação sobre conferência: comparado com extrações manuais, os dados batem 100%.
Diferenças eventuais são de ATUALIZAÇÃO do sistema entre um download e outro
(ex.: abastecimentos lançados depois, reconciliação de passageiros na catraca).
"""

import sys
import os
import re
import json
import base64
import hashlib
import datetime
from html.parser import HTMLParser

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:                       # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry


def _mount_retry(session, read_retry=1):
    """Adiciona retry de CONEXÃO (DNS/connect) e 5xx à sessão. read_retry=0 nas
    mutations (evita duplicar se o INSERT chegou mas a resposta deu timeout)."""
    retry = Retry(total=None, connect=5, read=read_retry, status=3,
                  backoff_factor=1.5, status_forcelist=[502, 503, 504],
                  allowed_methods=None, raise_on_status=False)
    ad = HTTPAdapter(max_retries=retry)
    session.mount("https://", ad)
    session.mount("http://", ad)
    return session


# ────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ────────────────────────────────────────────────────────────────────────────
PASTA_SAIDA = r"C:\Users\User\Downloads\Relatorios_SGT"

# Período padrão (modo automático): hoje-DIAS_INICIO .. hoje-DIAS_FIM
# D+1 DIÁRIO: pega SÓ o dia anterior (ontem), enquanto o relatório do SGT ainda
# está detalhado (o SGT consolida dias fechados ~2-3 dias depois, perdendo os
# reabastecimentos extras do mesmo veículo/dia). Rodar todo dia de manhã.
DIAS_INICIO = 1   # ontem
DIAS_FIM    = 1   # ontem

# Quais relatórios gerar
RELATORIOS = ["abastecimento", "viagens"]

# Excluir linhas-ponte (descontinuidade de hodômetro) SÓ para estas empresas, p/
# bater com intaceabast. Pendotiba (863) e Araçatuba (914) NÃO entram aqui porque
# o intaceabast delas está DUPLICADO (não serve de alvo) — nelas sobe tudo.
EMPRESAS_FILTRAR_PONTE = {924, 926}   # Ponte Coberta, N.S. Glória

# Campos EXTRAS no gravaIntAceAbast (alem do minimo dia/nr_carro/hodo/km/kml/diesel):
# chassi/motor/valorabast sao ACEITOS pela mutation (o processPendotibaVei os envia).
# 'turno' (col Tur.) e INCERTO — se a mutation rejeitar, ponha ENVIAR_TURNO_ABAST=False.
ENVIAR_CHASSI_MOTOR_VALOR = True
ENVIAR_TURNO_ABAST        = False   # 'turno' NAO existe no IntAceAbastInput (mutation rejeita)

# IDs do Abastecimento (iguais em todas as instâncias observadas)
ABAST = {"ctrl": "frota.abastecimento.CRelatorioAbastecimentoVeiculo",
         "idfunc": "503234", "idmod": "416", "dt_ini": "dtInicial", "dt_fim": "dtFinal"}
# Viagens: o ctrl é o mesmo, mas idfunc/idmod MUDAM por instância (ver INSTANCIAS)
VIAGENS_CTRL = "trafego.CRelatorioViagemRealizadaFuncionario"

INSTANCIAS = {
    "grupopontecoberta": {
        "host":    "https://grupopontecoberta.transoft.com.br/sgtweb/index.php",
        "conexao": "grupopontecoberta",
        "usuario": os.environ.get("SGT_GPC_USER", "copilot"),
        "senha":   os.environ.get("SGT_GPC_PASS", "abc*123"),
        "viagens": {"idfunc": "502868", "idmod": "502600"},
        # setores de abastecimento existentes (value interno -> rótulo)
        "setores_abast": {"23": "Gardel", "1": "Mesquita", "41": "Externo"},
        # TODAS as empresas que existem no SGT (p/ 'empresas1'/não-selecionadas ficar
        # correto mesmo rodando 1 empresa por vez). Sem isso, filtrar 1 empresa deixa
        # 'empresas1' vazio e o SGT ignora o filtro (traz todas).
        "empresas_sgt": ["001", "002", "003", "004"],
        "empresas": {
            "001": {"rotulo": "Ponte_Coberta", "setor_abast": "1", "sempresa_id": 924},   # Mesquita
            "002": {"rotulo": "NS_Gloria",     "setor_abast": "1", "sempresa_id": 926},   # Mesquita
        },
    },
    "pendotiba": {
        "host":    "https://pendotiba.transoft.com.br/sgtweb/index.php",
        "conexao": "pendotiba",
        "usuario": os.environ.get("SGT_PEN_USER", "copilot"),
        "senha":   os.environ.get("SGT_PEN_PASS", "123456"),
        "viagens": {"idfunc": "501965", "idmod": "92"},
        "setores_abast": {"21": "Garagem Pendotiba", "22": "Setor Arla",
                          "42": "Garagem Araçatuba", "43": "Arla Araçatuba",
                          "44": "Motor Araçatuba"},
        "empresas_sgt": ["001", "004"],   # todas as empresas no SGT desta instância
        "empresas": {
            "001": {"rotulo": "Pendotiba", "setor_abast": "21", "sempresa_id": 863},   # Garagem Pendotiba
            "004": {"rotulo": "Aracatuba", "setor_abast": "42", "sempresa_id": 914},   # Garagem Araçatuba
        },
    },
}

# ────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO ACE (import p/ o backend, replicando integracao-ace.component.ts)
# ────────────────────────────────────────────────────────────────────────────
# Só o ABASTECIMENTO é integrado: no frontend o caminho de Veículos está ATIVO
# (mutation gravaIntAceAbast) e o CSV do SGT já traz km/hodo/diesel/kml prontos.
# VIAGENS NÃO é integrado: o parser SGT (processMotHierarchical) mira a mutation
# gravaIntACEMotV2, que está COMENTADA no frontend (backend ainda não pronto);
# a mutation ativa gravaIntAceMot espera outro formato (sem roleta). Disparar
# apaga-dia + grava numa mutation inexistente arriscaria apagar sem reinserir.
INTEGRACAO = {
    "ativar": False,          # True = executa a integração após baixar
    "viagens": False,         # True = também integra funcionários (gravaIntAceMot)
    "modo": "dry-run",        # "dry-run" = só gera o payload das mutations p/ conferência
                              # "real"    = dispara de verdade (faz login automático)
    "graphql_url": "https://wws.copiloto.com.br/node",  # GraphQL público copiloto (login + mutations)
    # Login automático: o token é dinâmico (muda diariamente), então é obtido a cada
    # execução. pwc já vem criptografado (AES) — usar verbatim.
    "login_user": os.environ.get("ACE_LOGIN_USER", "monitoramento"),
    "login_pwc":  os.environ.get("ACE_LOGIN_PWC", "U2FsdGVkX1+nNqK/6auUDI079nDGuqpl8XwcGd4ENj0="),
    "token": "",              # preenchido automaticamente pelo login (deixar vazio)
    "sUsuarioId": 0,          # preenchido automaticamente pelo login (deixar 0)
    "tipoProc": 1,            # 1=ReIntegrar, 2=ReProcessar (afeta stsproc do log)
    "data_fmt": "%Y/%m/%d",   # formato do campo 'dia' nas mutations (padrão Matias yyyy/mm/dd)
    "concorrencia": 5,        # nº de gravações em paralelo (igual ao frontend)
    "pasta_payload": r"C:\Users\User\Downloads\Relatorios_SGT\_integracao",  # dry-run
}

# Separador interno dos campos multi-seleção do SGT: «¦|¦» (bytes AB A6 7C A6 BB)
SEP = "\xab\xa6|\xa6\xbb"

# Definição de parsing/seções por relatório (para o JSON)
SECOES = {
    "abastecimento": [
        (r"Ve.culo\s*:\s*(\S+)\s+Tipo de Chassi:\s*(.*?)\s+Tipo de Motor:\s*(.*?)\s*$",
         ["veiculo", "tipo_chassi", "tipo_motor"]),
    ],
    "viagens": [
        (r"Funcion.rio\s*:\s*(\S+)\s*-\s*(.*?)\s*$", ["func_cracha", "func_nome"]),
        (r"Data\s*:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\w+)\s*$", ["data", "dia_semana"]),
    ],
}
# ────────────────────────────────────────────────────────────────────────────


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = []
        self._cur = None
        self._sel = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "input":
            name = a.get("name")
            if not name:
                return
            t = a.get("type", "text").lower()
            if t in ("button", "submit", "image", "file", "reset"):
                return
            if t in ("checkbox", "radio"):
                if "checked" in a:
                    self.fields.append((name, a.get("value", "on")))
                return
            self.fields.append((name, a.get("value", "")))
        elif tag == "select":
            self._cur = a.get("name")
            self._sel = None
        elif tag == "option" and self._cur is not None:
            if "selected" in a and self._sel is None:
                self._sel = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "select" and self._cur is not None:
            if not self._cur.startswith("lst") and self._sel is not None:
                self.fields.append((self._cur, self._sel))
            self._cur = None


def _set(fields, name, value):
    out, done = [], False
    for n, v in fields:
        if n == name and not done:
            out.append((n, value)); done = True
        else:
            out.append((n, v))
    if not done:
        out.append((name, value))
    return out


def _lista(codigos):
    return "".join(c + SEP for c in codigos)


def login(inst):
    s = _mount_retry(requests.Session(), read_retry=2)   # downloads: retry conexão + leitura
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
    s.get(inst["host"], timeout=60)
    payload = {
        "hdnFoto": "",
        "hdnEdtLogin": base64.b64encode(inst["usuario"].encode("latin1")).decode(),
        "hdnEdtSenha": hashlib.md5(inst["senha"].encode("latin1")).hexdigest(),
        "teProtocolo": "https:",
        "edtLoginCPF": "",
        "edtConexao": inst["conexao"],
    }
    r = s.post(inst["host"] + "?c=controleAcesso.CLogin&m=validarLogin",
               data=payload, timeout=30, allow_redirects=False)
    loc = r.headers.get("Location") or ""
    # sucesso = redirect que NÃO volta para a tela de login/validação de senha.
    # (algumas instâncias redirecionam p/ "verTelaVerificarEmail" e mesmo assim
    #  a sessão já é válida para acessar os relatórios.)
    if r.status_code != 302 or "validarLogin" in loc or "verLogin" in loc:
        raise RuntimeError(f"Falha no login (status {r.status_code}, dest={loc!r}).")
    return s


def gerar_csv(s, inst, relatorio, empresa):
    if relatorio == "abastecimento":
        ctrl, idfunc, idmod = ABAST["ctrl"], ABAST["idfunc"], ABAST["idmod"]
        dt_ini_f, dt_fim_f = ABAST["dt_ini"], ABAST["dt_fim"]
    else:
        ctrl = VIAGENS_CTRL
        idfunc, idmod = inst["viagens"]["idfunc"], inst["viagens"]["idmod"]
        dt_ini_f, dt_fim_f = "dtInicio", "dtFim"

    url_form = f"{inst['host']}?c={ctrl}&m=verPesquisar&idFuncaoLog={idfunc}&idModulo={idmod}"
    html = s.get(url_form, timeout=60).content.decode("latin1")
    p = _FormParser(); p.feed(html)
    f = p.fields

    # empresa: selecionada em X2, as demais da instância em X1
    todas = inst.get("empresas_sgt") or list(inst["empresas"].keys())
    outras = [c for c in todas if c != empresa]
    f = _set(f, "empresas2", _lista([empresa]))
    f = _set(f, "empresas1", _lista(outras))

    if relatorio == "abastecimento":
        # filtra o SETOR DA GARAGEM da empresa; os demais setores vão em X1
        setor = inst["empresas"][empresa]["setor_abast"]
        outros_set = [v for v in inst["setores_abast"] if v != setor]
        f = _set(f, "setorAbastecimento2", _lista([setor]))
        f = _set(f, "setorAbastecimento1", _lista(outros_set))
    else:
        # viagens: todos os setores funcionais (zera os dois lados => "Todas")
        f = _set(f, "dsSetorFuncional2", "")
        f = _set(f, "dsSetorFuncional1", "")

    f = _set(f, dt_ini_f, GLOB_DT_INI)
    f = _set(f, dt_fim_f, GLOB_DT_FIM)

    enc = [(n, v.encode("latin1")) for n, v in f]
    s.post(f"{inst['host']}?c={ctrl}&itemMenu={idfunc}&m=pesquisar",
           data=enc, timeout=240, allow_redirects=False)
    r = s.get(f"{inst['host']}?c={ctrl}&itemMenu={idfunc}&m=verRelatorio", timeout=240)
    if "csv" not in r.headers.get("Content-Type", "").lower():
        raise RuntimeError(f"Resposta não é CSV: {r.content[:150]!r}")
    return r.content


def _split_csv_line(line):
    return [c.strip() for c in re.findall(r'"([^"]*)"', line)]


def csv_para_json(texto, relatorio):
    secoes = SECOES[relatorio]
    linhas = texto.replace("\r", "").split("\n")
    cabecalho, registros, contexto, colunas = {}, [], {}, []
    fase_cab = True

    def eh_secao(l):
        for rx, campos in secoes:
            m = re.match(rx, l)
            if m:
                return dict(zip(campos, [g.strip() for g in m.groups()]))
        return None

    for l in linhas:
        st = l.strip()
        if not st or st.startswith("Total"):
            continue
        sec = eh_secao(st)
        if sec is not None:
            fase_cab = False
            if any(k in ("data", "dia_semana") for k in sec):
                contexto.update(sec)
            else:
                contexto = dict(sec)
            colunas = []
            continue
        if fase_cab and st.startswith('"'):
            cells = _split_csv_line(st)
            if len(cells) == 2:
                cabecalho[cells[0].rstrip(":").strip()] = cells[1]
                continue
        if st.startswith('"'):
            valores = _split_csv_line(st)
            if colunas:
                reg = dict(contexto)
                for i, val in enumerate(valores):
                    nome = colunas[i] if i < len(colunas) and colunas[i] else f"col{i}"
                    if nome in reg:
                        nome = f"{nome}_{i}"
                    reg[nome] = val
                registros.append(reg)
            else:
                registros.append({**contexto, "valores": valores})
            continue
        if ";" in st:
            partes = [p.strip() for p in st.split(";")]
            if colunas and len(colunas) == len(partes):
                colunas = [(a + " " + b).strip() or f"col{i}"
                           for i, (a, b) in enumerate(zip(colunas, partes))]
            else:
                colunas = partes
            fase_cab = False

    return {"cabecalho": cabecalho, "total_registros": len(registros),
            "registros": registros}


# ────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO — Abastecimento (Veículos)  →  gravaIntAceAbast
# Espelha processPendotibaVei + o pipeline ativo do integracao-ace.component.ts:
#   apagaDiaIntAceAbast (1x/dia) -> gravaIntAceAbast (concorrência) ->
#   gravaLogProcessamento(tp_resumo:0, stsproc:7) se 0 erros.
# ────────────────────────────────────────────────────────────────────────────
def _num(valor):
    """Replica pegaValor: remove separador de milhar '.', vírgula->ponto.
    Retorna string de literal numérico, ou None se vazio/não-numérico."""
    s = (valor or "").strip().replace(".", "").replace(",", ".")
    if s == "":
        return None
    try:
        float(s)
        return s
    except ValueError:
        return None


def _dia_iso(str_dia, fmt):
    """'04/08/26' -> formato configurado (padrão '2026/08/04')."""
    p = str_dia.strip().split("/")
    if len(p) != 3:
        return str_dia.strip()
    dd, mm, yy = p
    ano = int(yy) + 2000 if len(yy) <= 2 else int(yy)
    return datetime.date(ano, int(mm), int(dd)).strftime(fmt)


def registros_abast_from_csv(csv_bytes, fmt, excluir_ponte=False):
    """Parseia o CSV do SGT (Abastecimento) -> registros no shape de gravaIntAceAbast.
    Captura também as LINHAS DE CONTINUAÇÃO (2º+ abastecimento do mesmo veículo/dia,
    que vêm sem repetir a data): data em branco -> usa a última data do veículo.
    Se excluir_ponte=True, descarta linhas-ponte (km=0 E diesel=0 E hodo_ini !=
    hodo_fim do registro anterior do veículo = descontinuidade de hodômetro), para
    bater com intaceabast. Subtotais ("Total Veículo") nunca entram (após Total)."""
    def _z(x):
        return (x is None) or (float(x) == 0.0)
    linhas = csv_bytes.decode("latin1").split("\n")
    regs = []
    sts = 0; cont = 0; veiculo = ""; chassi = ""; motor = ""
    ult_dia = None; prev_hf = None
    for raw in linhas:
        lin = raw.replace('"', "")
        if lin.startswith("Ve") and "Tipo de Chassi" in lin:   # "Veículo : 002/6001  Tipo de Chassi: X  Tipo de Motor: Y"
            pos = lin.index("Tipo de Chassi")
            seg = lin[10:pos - 1].strip().split("/")
            veiculo = seg[1].strip() if len(seg) > 1 else ""
            chassi = motor = ""
            if "Tipo de Motor" in lin:
                pos2 = lin.index("Tipo de Motor")
                chassi = lin[pos + 15:pos2 - 1].strip()
                motor = lin[pos2 + 14:].strip()
            sts = 1; cont = 0; ult_dia = None; prev_hf = None
        elif cont >= 2:
            if lin.startswith("Total"):
                sts = 0; cont = 0
            else:
                tmp = lin.split(";")
                str_dia = tmp[0].strip() if tmp else ""
                hodo_ini = _num(tmp[1]) if len(tmp) > 1 else None
                hodo_fim = _num(tmp[2]) if len(tmp) > 2 else None
                km       = _num(tmp[3]) if len(tmp) > 3 else None
                diesel   = _num(tmp[4]) if len(tmp) > 4 else None
                kml      = _num(tmp[5]) if len(tmp) > 5 else None
                turno    = tmp[15].strip() if len(tmp) > 15 else ""   # col "Tur."
                valorab  = _num(tmp[16]) if len(tmp) > 16 else None   # col "Vl. Ab."
                if str_dia:
                    ult_dia = _dia_iso(str_dia, fmt)
                tem_dado = any(x is not None for x in (hodo_ini, hodo_fim, km, diesel, kml))
                # linha-ponte: km=0 E diesel=0 E NÃO é continuação de hodômetro.
                continuo = (prev_hf is not None and hodo_ini is not None
                            and float(hodo_ini) == prev_hf)
                ponte = excluir_ponte and _z(km) and _z(diesel) and not continuo
                if ult_dia and (str_dia or tem_dado) and not ponte:
                    regs.append({
                        "dia": ult_dia,
                        "nr_carro": veiculo,
                        "hodo_ini": hodo_ini,
                        "hodo_fim": hodo_fim,
                        "km":       km,
                        "diesel":   diesel,
                        "kml":      kml,
                        "chassi":   chassi,
                        "motor":    motor,
                        "turno":    turno,
                        "valorabast": valorab,
                    })
                if hodo_fim is not None:
                    prev_hf = float(hodo_fim)
        if sts >= 1:
            cont += 1
    return regs


def _registro_literal(reg):
    def v(x):
        return x if x is not None else "null"
    campos = [f'dia:"{reg["dia"]}"', f'nr_carro:"{reg["nr_carro"]}"',
              f'hodo_ini:{v(reg["hodo_ini"])}', f'hodo_fim:{v(reg["hodo_fim"])}',
              f'km:{v(reg["km"])}', f'kml:{v(reg["kml"])}', f'diesel:{v(reg["diesel"])}']
    if ENVIAR_CHASSI_MOTOR_VALOR:
        campos += [f'chassi:"{reg.get("chassi","")}"', f'motor:"{reg.get("motor","")}"',
                   f'valorabast:{v(reg.get("valorabast"))}']
    if ENVIAR_TURNO_ABAST:
        campos.append(f'turno:"{reg.get("turno","")}"')
    return "{" + ", ".join(campos) + "}"


def _mut_apaga(tok, emp, dia):
    return f'mutation {{ apagaDiaIntAceAbast(token:"{tok}", sEmpresaId:{emp}, dia:"{dia}") {{ respCode respMsg }} }}'

def _mut_grava(tok, emp, reg):
    return f'mutation {{ gravaIntAceAbast(token:"{tok}", sEmpresaId:{emp}, registro:{_registro_literal(reg)}) {{ respCode respMsg }} }}'

def _mut_log(tok, emp, dia, uid, qtde):
    return (f'mutation {{ gravaLogProcessamento(token:"{tok}", sEmpresaId:{emp}, tp_resumo:0, '
            f'dia:"{dia}", stsproc:7, sUsuarioId:{uid}, qtde:{qtde}, origem:"integracao_ace") {{ respCode respMsg }} }}')


def login_ace(cfg):
    """Faz login no GraphQL copiloto e devolve (token, userId). Token é dinâmico
    (muda diariamente), por isso é obtido a cada execução."""
    q = (f'{{ login(login:"{cfg["login_user"]}", pwc:"{cfg["login_pwc"]}", '
         f'emailTkn:"", matricula:"", codEmpresa:-1) '
         f'{{ token userId nivel errCode errMsg }} }}')
    s = _mount_retry(requests.Session(), read_retry=2)
    r = s.post(cfg["graphql_url"], json={"query": q}, timeout=60)
    j = r.json()
    if j.get("errors"):
        raise RuntimeError("login GraphQL: " + j["errors"][0].get("message", "erro"))
    lg = (j.get("data") or {}).get("login") or {}
    if lg.get("errCode"):
        raise RuntimeError(f"login recusado: {lg.get('errMsg')} (errCode {lg.get('errCode')})")
    token = lg.get("token") or ""
    user_id = lg.get("userId") or 0
    if not token:
        raise RuntimeError("login sem token na resposta")
    return token, int(user_id)


def integrar_abastecimento(csv_bytes, sempresa_id, rotulo, tag, cfg):
    regs = registros_abast_from_csv(csv_bytes, cfg["data_fmt"],
                                    excluir_ponte=sempresa_id in EMPRESAS_FILTRAR_PONTE)
    if not regs:
        return "  integracao: 0 registros (nada a fazer)"
    # Dias em ORDEM CRESCENTE (yyyy/mm/dd ordena como texto). Antes saía na
    # ordem de aparição no CSV do SGT (ex.: 19, 21, 20).
    dias = sorted(set(r["dia"] for r in regs))

    if cfg["modo"] == "dry-run":
        os.makedirs(cfg["pasta_payload"], exist_ok=True)
        caminho = os.path.join(cfg["pasta_payload"], f"integrar_abast_{rotulo}_{tag}.graphql")
        with open(caminho, "w", encoding="utf-8") as fp:
            fp.write(f"# DRY-RUN  empresa={rotulo} sEmpresaId={sempresa_id}  "
                     f"{len(regs)} registros, {len(dias)} dia(s): {', '.join(dias)}\n")
            fp.write(f"# token=<TOKEN>  sUsuarioId=<UID>  (preencha em INTEGRACAO p/ modo real)\n\n")
            # DIA A DIA, em ordem: apaga o dia -> grava o dia -> log do dia
            for d in dias:
                do_dia = [r for r in regs if r["dia"] == d]
                fp.write(f"# ===== dia {d} ({len(do_dia)} registros) =====\n")
                fp.write(_mut_apaga("<TOKEN>", sempresa_id, d) + "\n")
                for r in do_dia:
                    fp.write(_mut_grava("<TOKEN>", sempresa_id, r) + "\n")
                fp.write(_mut_log("<TOKEN>", sempresa_id, d, "<UID>", len(do_dia)) + "\n\n")
        return f"  integracao[dry-run]: {len(regs)} reg, {len(dias)} dia(s) -> {os.path.basename(caminho)}"

    # modo real
    for campo in ("graphql_url", "token", "sUsuarioId"):
        if not cfg.get(campo):
            return f"  integracao[real] ABORTADA: falta '{campo}' em INTEGRACAO"
    url, tok, uid = cfg["graphql_url"], cfg["token"], cfg["sUsuarioId"]
    _sess = _mount_retry(requests.Session(), read_retry=0)  # retry conexão, NÃO leitura (evita duplicar)

    def _post(query):
        r = _sess.post(url, json={"query": query}, timeout=120)
        j = r.json()
        if j.get("errors"):
            raise RuntimeError(j["errors"][0].get("message", "erro graphql"))
        return j

    # SEGURANÇA: grava 1 registro ANTES de apagar. Se a mutation rejeitar o shape
    # (ex.: campo novo chassi/motor/turno/valorabast nao aceito), aborta sem apagar.
    try:
        _post(_mut_grava(tok, sempresa_id, next(r for r in regs if r["dia"] == dias[0])))
    except Exception as e:
        return f"  integracao[real] ABORTADA na validação de shape: {e} (NADA foi apagado)"

    # DIA A DIA, em ordem crescente: apaga o dia -> grava os registros do dia
    # (sequencial, na ordem do CSV) -> log do dia (só se o dia teve 0 erro).
    # Se o apagaDia falhar, para ali: os dias seguintes nem são tocados.
    erros = 0
    feitos = 0
    for d in dias:
        do_dia = [r for r in regs if r["dia"] == d]
        try:
            _post(_mut_apaga(tok, sempresa_id, d))
        except Exception as e:
            return (f"  integracao[real] PAROU no apagaDia {d}: {e} "
                    f"({feitos} dia(s) já integrados; {d} e seguintes não foram tocados)")
        erros_dia = 0
        for reg in do_dia:
            try:
                _post(_mut_grava(tok, sempresa_id, reg))
            except Exception as e:
                erros_dia += 1
                print("    gravaIntAceAbast.err", d, reg, e)
        erros += erros_dia
        if erros_dia == 0:
            try:
                _post(_mut_log(tok, sempresa_id, d, uid, len(do_dia)))
            except Exception as e:
                print("    gravaLogProcessamento.err", d, e)
        else:
            print(f"    dia {d}: {erros_dia} erro(s) — log NÃO gravado")
        feitos += 1
        print(f"    abast {rotulo} {d}: {len(do_dia) - erros_dia}/{len(do_dia)} gravados", flush=True)
    return f"  integracao[real]: {len(regs)-erros}/{len(regs)} gravados ({erros} erro), {len(dias)} dia(s) em ordem"


# ────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO — Funcionários (Viagens)  →  gravaIntAceMot
# Porta processMotHierarchical (agrupa as viagens do SGT por funcionário/dia em
# turnos: 1ª pegada -> última largada) e mapeia p/ a mutation ATIVA gravaIntAceMot
# {dia, nr_carro, matricula, linha, hr_pegada, hr_largada, diesel}. (A gravaIntACEMotV2
# com roleta está comentada no backend; roleta não é gravada aqui, diesel vai null
# pois o relatório de viagens não traz consumo por turno.)
# Pipeline igual ao abast: apagaDiaIntAceMot -> gravaIntAceMot -> gravaLogProcessamento
# (tp_resumo:1, stsproc:7 = ReIntegrar, sem reprocessar).
# ────────────────────────────────────────────────────────────────────────────
def _pf(x):
    try:
        return float((x or "0").replace(",", ".")) or 0.0
    except (ValueError, AttributeError):
        return 0.0

def _vei_nmv(raw):
    # nr_carro do funcionário = valor cru (SEM inserir ponto), p/ bater com o
    # abastecimento (ex.: Ponte/Glória usam "190095", não "190.095").
    return (raw or "").strip()

def _parse_dt_br(d, hora):
    if not d or not hora:
        return None
    p = d.split("/")
    if len(p) < 3:
        return None
    ano = int(p[2]) + 2000 if int(p[2]) < 100 else int(p[2])
    hp = (hora or "").split(":")
    h = int(hp[0]) if hp[0].strip() else 0
    mi = int(hp[1]) if len(hp) > 1 and hp[1].strip() else 0
    return datetime.datetime(ano, int(p[1]), int(p[0]), h, mi)

def _fmt_dt(dt):
    return dt.strftime("%Y/%m/%d %H:%M:00") if dt else ""

def _fmt_dia(d):
    p = d.split("/")
    if len(p) == 3:
        ano = int(p[2]) + 2000 if int(p[2]) < 100 else int(p[2])
        return f"{ano}/{int(p[1]):02d}/{int(p[0]):02d}"
    return d


def registros_viagens_from_csv(csv_bytes):
    """Port de processMotHierarchical: viagens SGT -> turnos por funcionário/dia."""
    linhas = csv_bytes.decode("latin1").split("\n")
    regs = []
    strMat = strMot = data = ""
    sts = cont = 0
    prim = None
    ultLinha = ultHFim = ultNMV = ""
    ultRFim = ultRin = 0.0
    ultDt = None

    def calc_fim(hora_fim):
        dt = _parse_dt_br(data, hora_fim)
        if not dt:
            return None
        if prim and dt < prim:
            dt = dt + datetime.timedelta(days=1)
        return dt

    def add_reg(dt_ini, dt_fim, v_linha, v_nmv, v_rin, v_rfim):
        if not data or not dt_ini or not dt_fim:
            return
        regs.append({"dia": _fmt_dia(data), "nome": strMot, "matricula": strMat,
                     "nr_carro": v_nmv, "linha": v_linha,
                     "hr_pegada": _fmt_dt(dt_ini), "hr_largada": _fmt_dt(dt_fim),
                     "roletaIni": v_rin, "roletaFim": v_rfim})

    for raw in linhas:
        lin = raw.replace('"', "")
        sep = ";" if ";" in lin else ","
        cols = lin.split(sep)
        texto = lin.strip()

        if re.match(r"^Funcion.rio:", texto, re.I):
            emp = texto[texto.index(":") + 1:].strip()
            arr = emp.split("-")
            if len(arr) >= 2:
                strMat = arr[0].strip(); strMot = "-".join(arr[1:]).strip()
            sts = 1; cont = 0
            ultLinha = ultNMV = ultHFim = ""; ultRFim = ultRin = 0.0
            ultDt = None; prim = None
        elif strMat and sts >= 1:
            if texto.startswith("Data:"):
                data = texto[6:].split("-")[0].strip()
                cont = 0; sts = 1; prim = None
            elif cont == 3:
                hora_ini = (cols[0] if len(cols) > 0 else "").strip()
                ultLinha = (cols[1] if len(cols) > 1 else "").strip()
                ultHFim = (cols[3] if len(cols) > 3 else "").strip()
                ultRFim = _pf(cols[5] if len(cols) > 5 else "0")
                ultRin = ultRFim - _pf(cols[6] if len(cols) > 6 else "0")
                ultNMV = _vei_nmv(cols[22] if len(cols) > 22 else "")
                ultDt = _parse_dt_br(data, hora_ini)
                if not prim and ultDt:
                    prim = ultDt
            elif cont > 3 and sts == 1:
                nova_linha = (cols[1] if len(cols) > 1 else "").strip()
                novo_nmv = _vei_nmv(cols[22] if len(cols) > 22 else "")
                if texto.startswith("Total"):
                    add_reg(ultDt, calc_fim(ultHFim), ultLinha, ultNMV, ultRin, ultRFim)
                    sts = 2
                elif (ultLinha and nova_linha and ultLinha != nova_linha) or \
                     (ultNMV and novo_nmv and ultNMV != novo_nmv):
                    add_reg(ultDt, calc_fim(ultHFim), ultLinha, ultNMV, ultRin, ultRFim)
                    hora_ini2 = (cols[0] if len(cols) > 0 else "").strip()
                    ndt = _parse_dt_br(data, hora_ini2)
                    if prim and ndt and ndt < prim:
                        ndt = ndt + datetime.timedelta(days=1)
                    ultDt = ndt
                    r_fim2 = _pf(cols[5] if len(cols) > 5 else "0")
                    ultRin = r_fim2 - _pf(cols[6] if len(cols) > 6 else "0")
                    ultLinha = nova_linha or ultLinha; ultNMV = novo_nmv or ultNMV
                    ultHFim = (cols[3] if len(cols) > 3 else "").strip() or ultHFim
                    ultRFim = r_fim2 or ultRFim
                else:
                    ultHFim = (cols[3] if len(cols) > 3 else "").strip() or ultHFim
                    ultRFim = _pf(cols[5] if len(cols) > 5 else "0") or ultRFim
                    if nova_linha:
                        ultLinha = nova_linha
                    if novo_nmv:
                        ultNMV = novo_nmv
        if sts >= 1:
            cont += 1
    return regs


def _registro_mot_literal(reg):
    def q(x):
        return f'"{x}"' if x else "null"
    return (f'{{dia:"{reg["dia"]}", nr_carro:"{reg["nr_carro"]}", matricula:"{reg["matricula"]}", '
            f'linha:"{reg["linha"]}", hr_pegada:{q(reg["hr_pegada"])}, hr_largada:{q(reg["hr_largada"])}, '
            f'diesel:null}}')

def _mut_apaga_mot(tok, emp, dia):
    return f'mutation {{ apagaDiaIntAceMot(token:"{tok}", sEmpresaId:{emp}, dia:"{dia}") {{ respCode respMsg }} }}'

def _mut_grava_mot(tok, emp, reg):
    return f'mutation {{ gravaIntAceMot(token:"{tok}", sEmpresaId:{emp}, registro:{_registro_mot_literal(reg)}) {{ respCode respMsg }} }}'

def _mut_log_mot(tok, emp, dia, uid, qtde, stsproc=3):   # motorista: stsproc:3 (padrão)
    return (f'mutation {{ gravaLogProcessamento(token:"{tok}", sEmpresaId:{emp}, tp_resumo:1, '
            f'dia:"{dia}", stsproc:{stsproc}, sUsuarioId:{uid}, qtde:{qtde}, origem:"integracao_ace") {{ respCode respMsg }} }}')


def integrar_viagens(csv_bytes, sempresa_id, rotulo, tag, cfg):
    regs = registros_viagens_from_csv(csv_bytes)
    if not regs:
        return "  integracao[viagens]: 0 registros (nada a fazer)"
    # Dias em ORDEM CRESCENTE (yyyy/mm/dd ordena como texto).
    dias = sorted(set(r["dia"] for r in regs))
    # LOG do MOTORISTA: stsproc:3 SEMPRE (decisão 21/09/2026). O abast segue com
    # stsproc:7 fixo (ver _mut_log). Antes: 3 se tipoProc==2 senão 7 (regra frontend).
    stsproc = 3

    if cfg["modo"] == "dry-run":
        os.makedirs(cfg["pasta_payload"], exist_ok=True)
        caminho = os.path.join(cfg["pasta_payload"], f"integrar_viagens_{rotulo}_{tag}.graphql")
        with open(caminho, "w", encoding="utf-8") as fp:
            fp.write(f"# DRY-RUN viagens empresa={rotulo} sEmpresaId={sempresa_id} "
                     f"{len(regs)} reg, {len(dias)} dia(s): {', '.join(dias)}\n\n")
            # DIA A DIA, em ordem: apaga o dia -> grava o dia -> log do dia
            for d in dias:
                do_dia = [r for r in regs if r["dia"] == d]
                fp.write(f"# ===== dia {d} ({len(do_dia)} turnos, stsproc={stsproc}) =====\n")
                fp.write(_mut_apaga_mot("<TOKEN>", sempresa_id, d) + "\n")
                for r in do_dia:
                    fp.write(_mut_grava_mot("<TOKEN>", sempresa_id, r) + "\n")
                fp.write(_mut_log_mot("<TOKEN>", sempresa_id, d, "<UID>", len(do_dia), stsproc) + "\n\n")
        return f"  integracao[viagens dry-run]: {len(regs)} reg, {len(dias)} dia(s) -> {os.path.basename(caminho)}"

    for campo in ("graphql_url", "token", "sUsuarioId"):
        if not cfg.get(campo):
            return f"  integracao[viagens] ABORTADA: falta '{campo}'"
    url, tok, uid = cfg["graphql_url"], cfg["token"], cfg["sUsuarioId"]
    _sess = _mount_retry(requests.Session(), read_retry=0)  # retry conexão, NÃO leitura (evita duplicar)

    def _post(query):
        r = _sess.post(url, json={"query": query}, timeout=120)
        j = r.json()
        if j.get("errors"):
            raise RuntimeError(j["errors"][0].get("message", "erro graphql"))
        return j

    # SEGURANÇA: grava 1 registro ANTES de apagar. Se o backend rejeitar o shape,
    # aborta sem ter apagado nada (evita apagar o dia e não conseguir reinserir).
    try:
        _post(_mut_grava_mot(tok, sempresa_id, next(r for r in regs if r["dia"] == dias[0])))
    except Exception as e:
        return f"  integracao[viagens] ABORTADA na validação de shape: {e} (NADA foi apagado)"

    # DIA A DIA, em ordem crescente: apagaDiaIntAceMot -> gravaIntAceMot (dos
    # turnos do dia, sequencial) -> gravaLogProcessamento do dia (só se 0 erro).
    # Se o apagaDia falhar, para ali: os dias seguintes nem são tocados.
    erros = 0
    feitos = 0
    for d in dias:
        do_dia = [r for r in regs if r["dia"] == d]
        try:
            _post(_mut_apaga_mot(tok, sempresa_id, d))
        except Exception as e:
            return (f"  integracao[viagens] PAROU no apagaDia {d}: {e} "
                    f"({feitos} dia(s) já integrados; {d} e seguintes não foram tocados)")
        erros_dia = 0
        for reg in do_dia:
            try:
                _post(_mut_grava_mot(tok, sempresa_id, reg))
            except Exception as e:
                erros_dia += 1
                print("    gravaIntAceMot.err", d, reg.get("matricula"), e)
        erros += erros_dia
        if erros_dia == 0:
            try:
                _post(_mut_log_mot(tok, sempresa_id, d, uid, len(do_dia), stsproc))
            except Exception as e:
                print("    gravaLogProcessamento.err", d, e)
        else:
            print(f"    dia {d}: {erros_dia} erro(s) — log NÃO gravado")
        feitos += 1
        print(f"    viagens {rotulo} {d}: {len(do_dia) - erros_dia}/{len(do_dia)} gravados", flush=True)
    return f"  integracao[viagens]: {len(regs)-erros}/{len(regs)} gravados ({erros} erro), {len(dias)} dia(s) em ordem"


def main():
    global GLOB_DT_INI, GLOB_DT_FIM
    if len(sys.argv) >= 3:
        GLOB_DT_INI, GLOB_DT_FIM = sys.argv[1], sys.argv[2]
    else:
        hoje = datetime.date.today()
        GLOB_DT_INI = (hoje - datetime.timedelta(days=DIAS_INICIO)).strftime("%d/%m/%Y")
        GLOB_DT_FIM = (hoje - datetime.timedelta(days=DIAS_FIM)).strftime("%d/%m/%Y")

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    print(f"Período: {GLOB_DT_INI} até {GLOB_DT_FIM}")
    print(f"Saída:   {PASTA_SAIDA}\n")
    tag = f"{GLOB_DT_INI}_{GLOB_DT_FIM}".replace("/", "-")

    # login automático no copiloto p/ integração real (token dinâmico)
    if INTEGRACAO["ativar"] and INTEGRACAO["modo"] == "real":
        try:
            tok, uid = login_ace(INTEGRACAO)
            INTEGRACAO["token"] = tok
            INTEGRACAO["sUsuarioId"] = uid
            print(f"Login copiloto OK (userId={uid}); integração REAL ativa.\n")
        except Exception as e:
            print(f"Login copiloto FALHOU: {e}\n>> integração real abortada; seguindo só com download.\n")
            INTEGRACAO["ativar"] = False

    for nome_inst, inst in INSTANCIAS.items():
        print(f"########## INSTÂNCIA: {nome_inst} ##########")
        try:
            s = login(inst)
            print("  login OK")
        except Exception as e:
            print(f"  LOGIN FALHOU: {e}\n")
            continue

        for rel in RELATORIOS:
            for cod, info in inst["empresas"].items():
                rotulo = info["rotulo"]
                try:
                    csv_bytes = gerar_csv(s, inst, rel, cod)
                    base = f"{rel}_{rotulo}_{tag}"
                    with open(os.path.join(PASTA_SAIDA, base + ".csv"), "wb") as fp:
                        fp.write(csv_bytes)

                    dados = csv_para_json(csv_bytes.decode("latin1"), rel)
                    dados["meta"] = {"instancia": nome_inst, "relatorio": rel,
                                     "empresa": cod, "nome_empresa": rotulo,
                                     "dt_inicial": GLOB_DT_INI, "dt_final": GLOB_DT_FIM}
                    with open(os.path.join(PASTA_SAIDA, base + ".json"), "w",
                              encoding="utf-8") as fp:
                        json.dump(dados, fp, ensure_ascii=False, indent=2)

                    print(f"  [{rel:13} {rotulo:13}] OK  {len(csv_bytes):>9,} B CSV | "
                          f"{dados['total_registros']:>5} reg JSON")

                    # integração (só abastecimento; viagens não está pronto no backend)
                    if INTEGRACAO["ativar"] and rel == "abastecimento":
                        msg = integrar_abastecimento(csv_bytes, info["sempresa_id"],
                                                     rotulo, tag, INTEGRACAO)
                        print(msg)
                    elif INTEGRACAO["ativar"] and rel == "viagens":
                        if INTEGRACAO.get("viagens"):
                            print(integrar_viagens(csv_bytes, info["sempresa_id"],
                                                   rotulo, tag, INTEGRACAO))
                        else:
                            print("  integracao[viagens]: desligada (INTEGRACAO['viagens']=False)")
                except Exception as e:
                    print(f"  [{rel:13} {rotulo:13}] ERRO: {e}")
        print()

    print("Concluído.")


if __name__ == "__main__":
    main()
