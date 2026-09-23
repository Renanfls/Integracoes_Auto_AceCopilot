#!/usr/bin/env bash
# =============================================================
# Deploy do SGT -> ACE na maquina 2.152
# - garante /opt/sgt e /opt/sgt/logs
# - instala dependencia (requests)
# - fixa timezone America/Sao_Paulo
# - instala o crontab do usuario atual (idempotente)
# - dispara um teste manual: pendotiba (Pendotiba 001 + Aracatuba 004)
#
# USO (na 2.152, depois de copiar o pacote para /opt/sgt):
#   sudo bash /opt/sgt/deploy_2152.sh
#
# Reexecuvel: NAO duplica linhas no crontab.
# =============================================================
set -euo pipefail

BASE="${BASE:-/opt/sgt}"
PYBIN="${PYBIN:-/usr/bin/python3}"
CRON_USER="${SUDO_USER:-$USER}"

echo "[deploy] BASE=$BASE  PYBIN=$PYBIN  CRON_USER=$CRON_USER"

# 1) diretorios + permissoes
mkdir -p "$BASE/logs" "$BASE/saida"
chown -R "$CRON_USER":"$CRON_USER" "$BASE"

# 2) dependencia
if ! "$PYBIN" -c 'import requests' >/dev/null 2>&1; then
  echo "[deploy] instalando 'requests'..."
  if command -v pip3 >/dev/null 2>&1; then
    pip3 install -r "$BASE/requirements.txt" || pip3 install requests
  else
    "$PYBIN" -m pip install -r "$BASE/requirements.txt" || "$PYBIN" -m pip install requests
  fi
fi

# 3) fuso do servidor
if command -v timedatectl >/dev/null 2>&1; then
  timedatectl set-timezone America/Sao_Paulo || true
fi

# 4) crontab (idempotente — remove linhas antigas com o mesmo comando e reinsere)
TMP="$(mktemp)"
crontab -u "$CRON_USER" -l 2>/dev/null | \
  grep -v 'agendador_sgt.py grupopontecoberta' | \
  grep -v 'agendador_sgt.py pendotiba' > "$TMP" || true

cat >> "$TMP" <<EOF
# --- SGT -> ACE (instalado por deploy_2152.sh em $(date -Iseconds)) ---
# Ponte Coberta + N.S. Gloria — todo dia as 16h, EXCETO domingo
0 16 * * 1-6 cd $BASE && $PYBIN agendador_sgt.py grupopontecoberta all >> $BASE/logs/grupopontecoberta.log 2>&1
# Pendotiba + Aracatuba — todo dia as 8h e 12h
0 8,12 * * * cd $BASE && $PYBIN agendador_sgt.py pendotiba all >> $BASE/logs/pendotiba.log 2>&1
EOF

crontab -u "$CRON_USER" "$TMP"
rm -f "$TMP"

echo "[deploy] crontab do usuario $CRON_USER:"
crontab -u "$CRON_USER" -l | sed 's/^/    /'

# 5) TESTE IMEDIATO — Pendotiba + Aracatuba (instancia 'pendotiba' cobre as duas)
echo "[deploy] rodando teste: agendador_sgt.py pendotiba all"
LOG="$BASE/logs/pendotiba.$(date +%Y%m%d_%H%M%S).teste.log"
sudo -u "$CRON_USER" bash -lc "cd '$BASE' && '$PYBIN' agendador_sgt.py pendotiba all" \
  >> "$LOG" 2>&1 && echo "[deploy] teste OK — log: $LOG" \
  || { echo "[deploy] TESTE FALHOU — log: $LOG"; tail -n 60 "$LOG" || true; exit 1; }

echo "[deploy] done."
