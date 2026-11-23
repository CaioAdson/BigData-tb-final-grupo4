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

# Seguranca (semana 4): Kerberos. PLAINTEXT/nenhuma por padrao (ambiente de desenvolvimento).
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
KAFKA_KERBEROS_SERVICE_NAME = os.getenv("KAFKA_KERBEROS_SERVICE_NAME", "kafka")
KAFKA_KERBEROS_PRINCIPAL = os.getenv("KAFKA_KERBEROS_PRINCIPAL")
KAFKA_KERBEROS_KEYTAB = os.getenv("KAFKA_KERBEROS_KEYTAB")

ES_AUTH = os.getenv("ES_AUTH", "nenhuma").lower()  # nenhuma | kerberos
ES_KERBEROS_SERVICO = os.getenv("ES_KERBEROS_SERVICO", "HTTP@elasticsearch")
ES_KERBEROS_PRINCIPAL = os.getenv("ES_KERBEROS_PRINCIPAL")
ES_KERBEROS_KEYTAB = os.getenv("ES_KERBEROS_KEYTAB")


def kafka_seguranca() -> dict:
    """Parametros librdkafka para SASL/GSSAPI (Kerberos). Vazio em PLAINTEXT."""
    if KAFKA_SECURITY_PROTOCOL.upper() not in {"SASL_PLAINTEXT", "SASL_SSL"}:
        return {}
    c = {"security.protocol": KAFKA_SECURITY_PROTOCOL.upper(), "sasl.mechanisms": "GSSAPI",
         "sasl.kerberos.service.name": KAFKA_KERBEROS_SERVICE_NAME}
    if KAFKA_KERBEROS_PRINCIPAL:
        c["sasl.kerberos.principal"] = KAFKA_KERBEROS_PRINCIPAL
    if KAFKA_KERBEROS_KEYTAB:
        c["sasl.kerberos.keytab"] = KAFKA_KERBEROS_KEYTAB
    return c
