"""Consumidor Kafka -> Elasticsearch (RF08, RF09, RF10, RF11).

Garantias:
  * Offset so e confirmado (commit manual) DEPOIS que o lote foi gravado no Elasticsearch
    e as mensagens invalidas foram entregues na DLQ  -> at-least-once, sem perda (RF09).
  * _id deterministico + operacao 'index' -> reprocessar sobrescreve, nao duplica (RF10).
  * Mensagem invalida (JSON quebrado, campo faltando, rejeitada pelo mapping) vai para a DLQ
    com o motivo em header, e o fluxo continua (RF11).
  * Elasticsearch fora do ar: o lote e tentado de novo (backoff) sem commit.
"""
import json
import logging
import signal
import time

from confluent_kafka import Consumer, KafkaException, Producer
from elasticsearch import Elasticsearch, helpers
from elasticsearch import ConnectionError as ESConnectionError
from elasticsearch import ApiError, TransportError

from . import config
from .indice import garantir_indice
from .modelos import validar_documento

log = logging.getLogger("consumidor")
STATUS_TRANSITORIOS = {429, 502, 503, 504}
_rodando = True


def _parar(*_):
    global _rodando
    _rodando = False


def conectar_es() -> Elasticsearch:
    es = Elasticsearch(config.ES_URL, request_timeout=30)
    espera = 1
    while _rodando:
        try:
            es.info()
            return es
        except Exception as e:
            log.warning("Elasticsearch indisponivel (%s); nova tentativa em %ss", type(e).__name__, espera)
            time.sleep(espera)
            espera = min(espera * 2, 30)
    raise SystemExit(0)


def enviar_dlq(dlq: Producer, msg, motivo: str):
    dlq.produce(
        config.TOPICO_DLQ, key=msg.key(), value=msg.value(),
        headers=[("erro", motivo[:500].encode()), ("topico_origem", msg.topic().encode()),
                 ("particao", str(msg.partition()).encode()), ("offset", str(msg.offset()).encode())],
    )
    dlq.poll(0)
    log.warning("DLQ <- offset %s/%s: %s", msg.partition(), msg.offset(), motivo[:200])


def indexar_com_retry(es, acoes, max_tentativas=5):
    """Indexa em bulk. Falha de conexao: tenta indefinidamente (sem commit).
    Itens com erro transitorio: reenvia so eles. Retorna (n_ok, {id: motivo} de erros definitivos)."""
    definitivos, pendentes, tentativa, n_ok = {}, acoes, 0, 0
    while pendentes and _rodando:
        try:
            ok, erros = helpers.bulk(es, pendentes, raise_on_error=False, stats_only=False)
        except (ESConnectionError, TransportError, ApiError) as e:
            if isinstance(e, ApiError) and e.status_code not in STATUS_TRANSITORIOS:
                raise  # erro de requisicao nao e transitorio: nao commitar, nao mascarar
            log.error("falha ao falar com o Elasticsearch (%s); retry em 5s", type(e).__name__)
            time.sleep(5)
            continue
        n_ok += ok
        retry_ids = set()
        for item in erros:
            info = next(iter(item.values()))
            if info.get("status") in STATUS_TRANSITORIOS:
                retry_ids.add(info["_id"])
            else:
                definitivos[info["_id"]] = json.dumps(info.get("error"), ensure_ascii=False)
        pendentes = [a for a in pendentes if a["_id"] in retry_ids]
        if pendentes:
            tentativa += 1
            if tentativa >= max_tentativas:
                raise RuntimeError(f"{len(pendentes)} itens com erro transitorio apos {max_tentativas} tentativas")
            time.sleep(min(2 ** tentativa, 20))
    if pendentes:
        raise RuntimeError("encerrado antes de concluir o lote; offsets NAO confirmados")
    return n_ok, definitivos


def processar_lote(msgs, es, consumer, dlq) -> int:
    acoes, por_id = [], {}
    for m in msgs:
        if m.error():
            raise KafkaException(m.error())
        try:
            doc = json.loads(m.value())
        except (ValueError, TypeError) as e:
            enviar_dlq(dlq, m, f"json_invalido: {e}")
            continue
        erros = validar_documento(doc)
        if erros:
            enviar_dlq(dlq, m, "validacao: " + "; ".join(erros))
            continue
        acoes.append({"_op_type": "index", "_index": config.ES_INDICE, "_id": doc["id"], "_source": doc})
        por_id[doc["id"]] = m
    n_ok = 0
    if acoes:
        n_ok, definitivos = indexar_com_retry(es, acoes)
        for _id, motivo in definitivos.items():
            enviar_dlq(dlq, por_id[_id], "elasticsearch: " + motivo)
    dlq.flush(30)                          # DLQ entregue ANTES do commit
    consumer.commit(asynchronous=False)    # so agora o offset avanca
    return n_ok


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)
    es = conectar_es()
    if garantir_indice(es):
        log.info("indice '%s' criado", config.ES_INDICE)
    consumer = Consumer({
        "bootstrap.servers": config.KAFKA_BOOTSTRAP,
        "group.id": config.GRUPO_CONSUMIDOR,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    })
    dlq = Producer({"bootstrap.servers": config.KAFKA_BOOTSTRAP, "acks": "all", "enable.idempotence": True})
    consumer.subscribe([config.TOPICO_QUESTOES])
    log.info("consumindo '%s' (grupo %s) -> indice '%s'", config.TOPICO_QUESTOES, config.GRUPO_CONSUMIDOR, config.ES_INDICE)
    total, t0, ultimo_log = 0, time.time(), time.time()
    try:
        while _rodando:
            msgs = consumer.consume(num_messages=config.LOTE_CONSUMIDOR, timeout=1.0)
            if not msgs:
                continue
            total += processar_lote(msgs, es, consumer, dlq)
            if time.time() - ultimo_log > 10:
                dt = time.time() - t0
                log.info("indexados %d docs (media %.1f docs/s)", total, total / dt)
                ultimo_log = time.time()
    finally:
        log.info("encerrando; total indexado nesta execucao: %d", total)
        consumer.close()


if __name__ == "__main__":
    main()
