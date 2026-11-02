#!/usr/bin/env bash
# Estado do pipeline: docs no indice, lag do consumidor e mensagens na DLQ.
set -u; source .env
IDX=${ES_INDEX:-enade-questoes}; G=${KAFKA_GROUP_ID:-enade-indexador}
K="docker exec enade-kafka /opt/kafka/bin"
echo "== Elasticsearch ($IDX)"; curl -s "localhost:9200/$IDX/_count?pretty" | grep count
echo "== Lag do consumidor (grupo $G)"
$K/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group "$G" 2>/dev/null || echo "(grupo ainda nao existe)"
echo "== Mensagens na DLQ ($KAFKA_TOPIC_DLQ)"
$K/kafka-get-offsets.sh --bootstrap-server localhost:9092 --topic "$KAFKA_TOPIC_DLQ" 2>/dev/null \
  | awk -F: '{s+=$3} END{print s+0}'
