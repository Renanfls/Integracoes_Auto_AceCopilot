#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agendador do processo automatico SGT -> ACE (para o cron do Linux).

USO:
    python3 agendador_sgt.py <instancia> [empresa] [tipoProc]

  instancia : grupopontecoberta   (Ponte Coberta=001, N.S. Gloria=002)
              pendotiba           (Pendotiba=001, Aracatuba=004)
  empresa   : (opcional) codigo p/ rodar SO uma empresa: 001 / 002 / 004
              "all" ou omitido = todas as empresas da instancia
  tipoProc  : (opcional) 1=ReIntegrar (padrao) | 2=ReProcessar

JANELA DE REPROCESSO (termina SEMPRE em ONTEM — o dia atual nao entra):
  - Segunda-feira : 7 dias  (hoje-7 .. hoje-1)
  - Demais dias   : 3 dias  (hoje-3 .. hoje-1)

SAIDA (CSV/JSON/payloads): variavel de ambiente SGT_SAIDA, ou <dir do script>/saida.

Depende de: extrair_relatorios_sgt.py (no mesmo diretorio) e do pacote 'requests'.
"""
import os
import sys
import datetime
import importlib.util

BASE = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.environ.get("SGT_SAIDA", os.path.join(BASE, "saida"))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("grupopontecoberta", "pendotiba"):
        print("uso: agendador_sgt.py <grupopontecoberta|pendotiba> [empresa|all] [tipoProc]")
        sys.exit(2)
    instancia = sys.argv[1]
    empresa = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "all" else None
    tipoProc = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    spec = importlib.util.spec_from_file_location(
        "ex", os.path.join(BASE, "extrair_relatorios_sgt.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    # paths (Linux)
    os.makedirs(SAIDA, exist_ok=True)
    m.PASTA_SAIDA = SAIDA
    m.INTEGRACAO["pasta_payload"] = os.path.join(SAIDA, "_integracao")

    # janela de reprocesso, terminando SEMPRE em ONTEM (o dia atual ainda está em
    # andamento e NÃO entra na integração):
    #   segunda-feira -> 7 dias (hoje-7 .. hoje-1)
    #   demais dias   -> 3 dias (hoje-3 .. hoje-1)
    hoje = datetime.date.today()
    N = 7 if hoje.weekday() == 0 else 3          # weekday(): segunda=0
    dt_ini = (hoje - datetime.timedelta(days=N)).strftime("%d/%m/%Y")
    dt_fim = (hoje - datetime.timedelta(days=1)).strftime("%d/%m/%Y")

    # restringe a instancia (e, se pedido, a 1 empresa) — mantendo empresas_sgt
    # para o filtro de empresa continuar funcionando (empresas1 = as demais).
    inst = dict(m.INSTANCIAS[instancia])
    if empresa:
        if empresa not in inst["empresas"]:
            print(f"empresa {empresa} nao existe em {instancia}: {list(inst['empresas'])}")
            sys.exit(2)
        inst["empresas"] = {empresa: inst["empresas"][empresa]}
    m.INSTANCIAS = {instancia: inst}

    m.RELATORIOS = ["abastecimento", "viagens"]
    m.INTEGRACAO["ativar"] = True
    m.INTEGRACAO["viagens"] = True
    m.INTEGRACAO["modo"] = "real"
    m.INTEGRACAO["tipoProc"] = tipoProc
    m.INTEGRACAO["concorrencia"] = 3            # gentil com o backend

    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] AGENDADOR "
          f"instancia={instancia} empresa={empresa or 'todas'} "
          f"janela={dt_ini}..{dt_fim} (N={N} dias, {'SEGUNDA' if N==7 else 'normal'}) "
          f"tipoProc={tipoProc}", flush=True)

    sys.argv = ["run", dt_ini, dt_fim]
    m.main()


if __name__ == "__main__":
    main()
