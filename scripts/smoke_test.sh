#!/usr/bin/env bash
# Verifica se a infraestrutura esta de pe. Usa um topico temporario (smoke-test),
# sem tocar nos topicos do pipeline.
set -u
source .env 2>/dev/null || { echo "Crie o .env (cp .env.example .env)"; exit 1; }
ok(){ echo "  [OK]    $1"; }; fail(){ echo "  [FALHA] $1"; RC=1; }; RC=0
K="docker exec enade-kafka /opt/kafka/bin"

echo "Elasticsearch:"
curl -s localhost:9200/_cluster/health | grep -Eq '"status":"(green|yellow)"' && ok "cluster saudavel" || fail "cluster indisponivel"

echo "Redis:"
docker exec enade-redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping | grep -q PONG && ok "PONG" || fail "sem resposta"

echo "Kafka:"
T=$($K/kafka-topics.sh --bootstrap-server localhost:9092 --list 2>/dev/null)
echo "$T" | grep -qx "$KAFKA_TOPIC_QUESTOES" && ok "topico $KAFKA_TOPIC_QUESTOES" || fail "topico $KAFKA_TOPIC_QUESTOES ausente"
echo "$T" | grep -qx "$KAFKA_TOPIC_DLQ" && ok "topico $KAFKA_TOPIC_DLQ" || fail "topico $KAFKA_TOPIC_DLQ ausente"

echo "Round-trip Kafka (topico temporario):"
$K/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic smoke-test --partitions 1 --replication-factor 1 >/dev/null 2>&1
echo "ping" | docker exec -i enade-kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic smoke-test >/dev/null 2>&1
R=$($K/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic smoke-test --from-beginning --max-messages 1 --timeout-ms 15000 2>/dev/null)
[ "$R" = "ping" ] && ok "publicou e leu a mensagem" || fail "nao leu de volta a mensagem"
$K/kafka-topics.sh --bootstrap-server localhost:9092 --delete --topic smoke-test >/dev/null 2>&1
exit $RC
