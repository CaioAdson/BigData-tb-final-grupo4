# ENADE Search: plataforma distribuida de busca (UniCatolica, Big Data, AP2)

Equipe: Caio Adson Oliveira Pimentel, Maria Ingrid

## Subir o ambiente
```bash
cp .env.example .env        # edite REDIS_PASSWORD
docker compose up -d
./scripts/smoke_test.sh
```
Requisitos: Docker + Compose v2, ~4 GB de RAM livres. No Linux, se o Elasticsearch cair:
`sudo sysctl -w vm.max_map_count=262144`.

| Servico | URL / porta |
|---|---|
| Kafka (host) | localhost:29092 |
| Elasticsearch | http://localhost:9200 |
| Kibana | http://localhost:5601 |
| Redis | localhost:6379 |
| Redis Insight | http://localhost:5540 (host: `redis`, porta 6379) |

## Pipeline de ingestao (semana 2)
```bash
# 1) infraestrutura + consumidor (cria o indice sozinho)
docker compose up -d
docker compose up -d --build consumidor

# 2) teste rapido com PDFs SINTETICOS (ja em data/demo, nao sao dados do ENADE)
docker compose run --rm --build produtor --manifest /data/demo/manifest.csv
./scripts/verificar_pipeline.sh
curl "localhost:9200/enade-questoes/_search?q=etica&pretty"

# 3) acervo real: coloque os PDFs em data/raw/, copie data/manifest.exemplo.csv para data/manifest.csv
docker compose run --rm produtor --manifest /data/manifest.csv
```
Extrair sem Kafka (para inspecionar/validar): `cd ingestao && pip install -r requirements.txt &&
python -m enade.produtor --manifest ../data/manifest.csv --dry-run --saida extraidas.jsonl`

Testes unitarios: `cd ingestao && pip install -r requirements-dev.txt && python -m unittest discover -s tests -t .`

## Estrutura
- `docker-compose.yml`: infraestrutura
- `docs/ARQUITETURA.md`: decisoes de topologia e de extracao (base do relatorio)
- `ingestao/`: extrator, produtor, consumidor, definicao do indice e testes
- `data/`: manifesto e PDFs (`raw/` nao e versionado; `demo/` e sintetico)
- `scripts/`: utilitarios

## Seguranca no Git
Nenhum segredo e versionado: use `.env` (ignorado) e mantenha `.env.example` sem valores reais.
