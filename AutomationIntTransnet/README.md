# SGT -> ACE — pacote de deploy

Processo que extrai Abastecimento e Viagens do SGTweb/Transnet e integra no ACE (GraphQL).
**Documentação completa: `HANDOFF_SGT_ACE.md`.**

## Início rápido (Linux)
```bash
sudo mkdir -p /opt/sgt/logs && cd /opt/sgt
# extraia este zip aqui
pip3 install -r requirements.txt
sudo timedatectl set-timezone America/Sao_Paulo

# teste manual (um periodo fixo):  agendador usa a janela automatica,
# mas da p/ rodar o engine direto com datas:
python3 agendador_sgt.py grupopontecoberta all      # roda a janela do dia
python3 agendador_sgt.py pendotiba all

# agendar:
crontab -e     # cole o conteudo de crontab.example (ajuste caminhos)
```

## Conteúdo
- `extrair_relatorios_sgt.py` — engine (login SGT, download, parsing, mutations GraphQL)
- `agendador_sgt.py` — entry-point do cron (janela: segunda=7d, demais=3d, termina ontem)
- `requirements.txt` — dependência (`requests`)
- `.env.example` — 6 env vars de credenciais (opcional; há fallback embutido)
- `crontab.example` — linhas de cron por grupo
- `HANDOFF_SGT_ACE.md` — arquitetura, rotas GraphQL, pipeline, troubleshooting

## Credenciais
Lidas de env var com **fallback aos valores atuais** — roda sem configurar nada.
Para produção, defina as vars do `.env.example` (ex.: `/etc/sgt.env`) e, se quiser,
remova os fallbacks no engine. Ver §5.1 do handoff.
