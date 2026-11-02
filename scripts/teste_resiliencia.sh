#!/usr/bin/env bash
# RF09/RNF04: derruba o consumidor, publica, reinicia e confere que nada se perdeu.
# Para um volume util, use um manifesto grande (ou rode varias vezes com acervos diferentes).
set -u; source .env
IDX=${ES_INDEX:-enade-questoes}; M=${1:-/data/demo/manifest.csv}
conta(){ curl -s -XPOST "localhost:9200/$IDX/_refresh" >/dev/null; curl -s "localhost:9200/$IDX/_count" | sed -E 's/.*"count":([0-9]+).*/\1/'; }
echo "1) parando consumidor"; docker compose stop consumidor
echo "2) apagando indice para a contagem partir do zero"; curl -s -XDELETE "localhost:9200/$IDX" >/dev/null
docker compose run --rm consumidor python -m enade.indice --criar
echo "3) publicando com consumidor FORA do ar"; docker compose run --rm produtor --manifest "$M" 2>&1 | tail -1
echo "   docs no indice (esperado 0): $(conta)"
echo "4) reiniciando consumidor (deve retomar do offset commitado)"; docker compose up -d consumidor; sleep 15
echo "   docs no indice: $(conta)"; ./scripts/verificar_pipeline.sh
