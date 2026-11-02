"""Configuracao via variaveis de ambiente (nenhum segredo no codigo)."""
import os
from pathlib import Path

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
TOPICO_QUESTOES = os.getenv("KAFKA_TOPIC_QUESTOES", "enade.questoes")
TOPICO_DLQ = os.getenv("KAFKA_TOPIC_DLQ", "enade.questoes.dlq")
GRUPO_CONSUMIDOR = os.getenv("KAFKA_GROUP_ID", "enade-indexador")

ES_URL = os.getenv("ES_URL", "http://localhost:9200")
ES_INDICE = os.getenv("ES_INDEX", "enade-questoes")
ES_SHARDS = int(os.getenv("ES_SHARDS", "3"))
ES_REPLICAS = int(os.getenv("ES_REPLICAS", "0"))

LOTE_CONSUMIDOR = int(os.getenv("CONSUMER_BATCH", "100"))
DIR_MAPPING = Path(os.getenv("MAPPING_DIR", Path(__file__).resolve().parent.parent / "mapping"))
