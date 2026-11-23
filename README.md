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

## API (FastAPI) - http://localhost:8001/docs
```bash
docker compose up -d                       # Elasticsearch, Redis, Kafka, LDAP (+ seed) e API
docker compose up -d --build api ldap-init # apos mudar a API ou o seed do LDAP
curl localhost:8001/api/health
```
- Swagger: http://localhost:8001/docs (botao **Authorize** aceita o token do login) e http://localhost:8001/redoc
- Contrato completo para o frontend (rotas, parametros, respostas, erros, perfis): [`docs/API.md`](docs/API.md)
- Exemplos JSON reais (dados simulados para o frontend): [`api/exemplos/`](api/exemplos)
- Seguranca (LDAP, perfis, Kerberos): [`docs/SEGURANCA.md`](docs/SEGURANCA.md)

Usuarios de demonstracao criados no LDAP pelo `ldap-init` (senhas definidas no seu `.env`):

| Login | Perfil | Senha |
|---|---|---|
| `prof.demo` | professor | `LDAP_SENHA_PROFESSOR_DEMO` |
| `aluno.demo` | estudante | `LDAP_SENHA_ESTUDANTE_DEMO` |

```bash
TOKEN=$(curl -s localhost:8001/api/auth/login -H 'Content-Type: application/json'   -d '{"usuario":"prof.demo","senha":"<LDAP_SENHA_PROFESSOR_DEMO>"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "localhost:8001/api/questoes?q=algoritmos&area=Computa%C3%A7%C3%A3o&ano=2021" -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8001/api/carrinho/questoes -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"id":"sistemas-de-informacao-demo-2021-ce-004"}'
curl -s "localhost:8001/api/carrinho/exportar?formato=pdf" -H "Authorization: Bearer $TOKEN" -o simulado.pdf
```

### Variaveis de ambiente da API
| Variavel | Padrao | Descricao |
|---|---|---|
| `ES_URL` | `http://localhost:9200` | URL do Elasticsearch |
| `ES_INDEX` | `enade-questoes` | indice das questoes |
| `ES_TIMEOUT` | `10` | timeout (s) das consultas |
| `ES_AUTH` | `nenhuma` | `nenhuma` ou `kerberos` (autenticacao mutua SPNEGO) |
| `ES_KERBEROS_SERVICO` | `HTTP@elasticsearch` | servico Kerberos do Elasticsearch |
| `ES_KERBEROS_PRINCIPAL` | - | principal da API (ex.: `api@ENADE.LOCAL`) |
| `ES_KERBEROS_KEYTAB` | - | keytab da API (ex.: `/keytabs/api.keytab`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis (cache, sessoes, carrinho) |
| `REDIS_PASSWORD` | - | senha do Redis (**segredo**, so no `.env`) |
| `CACHE_TTL` | `300` | validade (s) das consultas em cache |
| `SESSAO_TTL` | `3600` | inatividade (s) ate a sessao e o carrinho expirarem |
| `CARRINHO_MAX` | `100` | maximo de questoes por carrinho |
| `LDAP_URL` | `ldap://localhost:389` | servidor LDAP |
| `LDAP_BIND_DN` | - | conta de servico para buscar usuarios (vazio = bind anonimo) |
| `LDAP_BIND_PASSWORD` | - | senha da conta de servico (**segredo**) |
| `LDAP_USUARIOS_DN` | `ou=usuarios,dc=enade,dc=local` | base de busca de usuarios |
| `LDAP_GRUPOS_DN` | `ou=grupos,dc=enade,dc=local` | base dos grupos |
| `LDAP_ATRIBUTO_USUARIO` | `uid` | atributo do login |
| `LDAP_GRUPO_PROFESSOR` / `LDAP_GRUPO_ESTUDANTE` | `professores` / `estudantes` | grupos que definem o perfil |
| `LDAP_TIMEOUT` | `5` | timeout (s) do LDAP |
| `LOGIN_MAX_FALHAS` / `LOGIN_JANELA_BLOQUEIO` | `5` / `300` | bloqueio temporario apos senhas erradas |
| `CORS_ORIGENS` | localhost:5173/5174 | origens do frontend, separadas por virgula |

Variaveis so do `docker-compose` (todas no `.env`, nunca versionadas): `LDAP_ADMIN_PASSWORD`,
`LDAP_SENHA_PROFESSOR_DEMO`, `LDAP_SENHA_ESTUDANTE_DEMO`, `KRB5_MASTER_PASSWORD`, `ELASTIC_PASSWORD`.

### Testes da API
```bash
cd api && pip install -r requirements-dev.txt
python -m pytest                      # unitarios: Elasticsearch/LDAP simulados + fakeredis
python gerar_exemplos.py              # regenera api/exemplos/ se o contrato mudar

# integracao com servicos reais (relevancia PT-BR, Redis, LDAP): defina as URLs de teste
ES_TEST_URL=http://localhost:9200 REDIS_TEST_URL=redis://:<senha>@localhost:6379/15 LDAP_TEST_URL=ldap://localhost:389 LDAP_TEST_BIND_DN=cn=leitura,dc=enade,dc=local LDAP_TEST_BIND_PASSWORD=<...> LDAP_TEST_SENHA_PROFESSOR=<...> LDAP_TEST_SENHA_ESTUDANTE=<...> python -m pytest tests/test_integracao.py

./scripts/teste_kerberos.sh           # ponta a ponta com Kerberos (Kafka + Elasticsearch + API)
```

## Estrutura
- `docker-compose.yml`: infraestrutura
- `docs/ARQUITETURA.md`: decisoes de topologia e de extracao (base do relatorio)
- `api/`: API FastAPI (`app/`), testes (`tests/`) e exemplos JSON do contrato (`exemplos/`)
- `infra/`: seed do LDAP e KDC/configuracao Kerberos
- `ingestao/`: extrator, produtor, consumidor, definicao do indice e testes
- `data/`: manifesto e PDFs (`raw/` nao e versionado; `demo/` e sintetico)
- `scripts/`: utilitarios

## Seguranca no Git
Nenhum segredo e versionado: use `.env` (ignorado) e mantenha `.env.example` sem valores reais.
Keytabs Kerberos sao gerados pelo KDC em `secrets/keytabs/` (ignorado pelo Git).
