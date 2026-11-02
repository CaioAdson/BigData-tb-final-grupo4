#!/usr/bin/env bash
# RF10: publicar o mesmo manifesto duas vezes NAO pode aumentar o numero de documentos.
set -u; source .env
IDX=${ES_INDEX:-enade-questoes}; M=${1:-/data/demo/manifest.csv}
conta(){ curl -s "localhost:9200/$IDX/_count" | sed -E 's/.*"count":([0-9]+).*/\1/'; }
docker compose run --rm produtor --manifest "$M" >/dev/null 2>&1; sleep 8
curl -s -XPOST "localhost:9200/$IDX/_refresh" >/dev/null; A=$(conta)
docker compose run --rm produtor --manifest "$M" >/dev/null 2>&1; sleep 8
curl -s -XPOST "localhost:9200/$IDX/_refresh" >/dev/null; B=$(conta)
echo "docs apos 1a execucao: $A | apos 2a execucao: $B"
[ "$A" = "$B" ] && [ "$A" -gt 0 ] && echo "[OK] idempotente" || { echo "[FALHA]"; exit 1; }
