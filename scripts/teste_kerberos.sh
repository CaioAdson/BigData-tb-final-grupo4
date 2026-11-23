#!/usr/bin/env bash
# Teste ponta a ponta da integracao Kerberos (Kafka SASL/GSSAPI + Elasticsearch SPNEGO + API).
# Pre-requisito: .env preenchido (KRB5_MASTER_PASSWORD, ELASTIC_PASSWORD, LDAP_*, REDIS_PASSWORD).
# Uso: ./scripts/teste_kerberos.sh            (sobe a pilha segura, testa e deixa rodando)
#      ./scripts/teste_kerberos.sh --derrubar  (no fim derruba tudo e apaga volumes)
set -u
cd "$(dirname "$0")/.."
source .env 2>/dev/null || { echo "Crie o .env (cp .env.example .env)"; exit 1; }
DC="docker compose -f docker-compose.yml -f docker-compose.kerberos.yml"
ok(){ echo "  [OK]    $1"; }; fail(){ echo "  [FALHA] $1"; RC=1; }; RC=0
K="docker exec enade-kafka /opt/kafka/bin"
CFG="--command-config /etc/kafka-kerberos/kafka-cliente.properties"

echo "Subindo pilha com Kerberos..."
mkdir -p secrets/keytabs
$DC up -d --build kdc kafka kafka-init elasticsearch es-init redis ldap ldap-init api >/dev/null 2>&1 || { $DC ps; exit 1; }
$DC up -d --build consumidor >/dev/null 2>&1
for i in $(seq 1 60); do curl -sf localhost:8001/ >/dev/null && break; sleep 3; done

echo "1. KDC e keytabs:"
for k in kafka HTTP api consumidor produtor kafka-admin; do
  [ -s "secrets/keytabs/$k.keytab" ] && ok "keytab $k" || fail "keytab $k ausente"
done

echo "2. Kafka exige SASL/GSSAPI:"
$K/kafka-topics.sh --bootstrap-server kafka:9092 $CFG --list 2>/dev/null | grep -qx "$KAFKA_TOPIC_QUESTOES" \
  && ok "cliente Kerberos (kafka-admin@ENADE.LOCAL) listou os topicos" || fail "cliente Kerberos nao conectou"
docker exec enade-kafka env KAFKA_OPTS= timeout 20 /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list >/dev/null 2>&1 \
  && fail "cliente SEM Kerberos conseguiu acessar o Kafka" || ok "cliente sem Kerberos foi recusado"

echo "3. Elasticsearch exige autenticacao:"
S=$(docker exec enade-api python -c "import urllib.request as u
try: u.urlopen('http://elasticsearch:9200/_cluster/health'); print(200)
except Exception as e: print(getattr(e,'code','erro'))")
[ "$S" = "401" ] && ok "requisicao anonima recusada (401)" || fail "requisicao anonima retornou $S"

echo "4. API <-> Elasticsearch com autenticacao mutua:"
H=$(curl -s localhost:8001/api/health)
echo "$H" | grep -q '"elasticsearch":"online"' && echo "$H" | grep -q '"autenticacao_elasticsearch":"kerberos"' \
  && ok "API autenticada via Kerberos: $H" || fail "health da API: $H"
docker logs enade-api 2>&1 | grep -q "autenticacao mutua com HTTP@elasticsearch concluida" \
  && ok "log da API confirma autenticacao mutua" || fail "log de autenticacao mutua ausente"
docker exec -e ES_KERBEROS_SERVICO=HTTP@kafka enade-api python -c "
import asyncio, os
from app.seguranca.kerberos import ProvedorTokenKerberos
p = ProvedorTokenKerberos('http://elasticsearch:9200', os.environ['ES_KERBEROS_SERVICO'], 'api@ENADE.LOCAL', '/keytabs/api.keytab')
asyncio.run(p.obter_token())" >/dev/null 2>&1 \
  && fail "API aceitou servidor com identidade errada" || ok "ticket para servico errado (HTTP@kafka) foi recusado"

echo "5. Pipeline Kerberos: produtor -> Kafka -> consumidor -> Elasticsearch -> API:"
$DC run --rm --build produtor --manifest /data/demo/manifest.csv >/dev/null 2>&1 \
  && ok "produtor@ENADE.LOCAL publicou no Kafka" || fail "produtor falhou"
login(){ curl -s localhost:8001/api/auth/login -H 'Content-Type: application/json' -d "{\"usuario\":\"$1\",\"senha\":\"$2\"}"   | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'; }
PROF=$(login prof.demo "$LDAP_SENHA_PROFESSOR_DEMO"); ALUNO=$(login aluno.demo "$LDAP_SENHA_ESTUDANTE_DEMO")
for i in $(seq 1 30); do
  # o consumidor indexa depois; invalida o cache (professor) para nao ler o resultado vazio anterior
  curl -s -X POST localhost:8001/api/cache/invalidar -H "Authorization: Bearer $PROF" >/dev/null
  T=$(curl -s "localhost:8001/api/questoes?tamanho=1" | sed -n 's/^{"total":\([0-9]*\).*/\1/p')
  [ "${T:-0}" -gt 0 ] && break; sleep 3
done
[ "${T:-0}" -gt 0 ] && ok "API retorna $T questoes indexadas pelo consumidor@ENADE.LOCAL" || fail "nenhuma questao indexada"

echo "6. LDAP e perfis na pilha segura:"
[ -n "$PROF" ] && [ -n "$ALUNO" ] && ok "login LDAP de prof.demo e aluno.demo" || fail "login LDAP falhou"
C=$(curl -s -o /dev/null -w '%{http_code}' localhost:8001/api/painel/professor -H "Authorization: Bearer $ALUNO")
[ "$C" = "403" ] && ok "estudante no painel do professor -> 403" || fail "estudante no painel -> $C"
C=$(curl -s -o /dev/null -w '%{http_code}' localhost:8001/api/painel/professor -H "Authorization: Bearer $PROF")
[ "$C" = "200" ] && ok "professor no painel -> 200" || fail "professor no painel -> $C"

if [ "${1:-}" = "--derrubar" ]; then $DC down -v >/dev/null 2>&1; fi
[ $RC -eq 0 ] && echo "TODOS OS TESTES KERBEROS PASSARAM" || echo "HA FALHAS"
exit $RC
