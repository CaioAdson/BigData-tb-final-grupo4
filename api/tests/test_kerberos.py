"""Autenticacao mutua API <-> Elasticsearch (Kerberos/SPNEGO), com contexto GSSAPI simulado.

O teste ponta a ponta (KDC + Kafka SASL/GSSAPI + Elasticsearch com realm Kerberos)
esta em scripts/teste_kerberos.sh e roda com docker-compose.kerberos.yml.
"""
import asyncio
import base64
import time

import pytest

from app.seguranca.kerberos import FalhaAutenticacaoMutua, ProvedorTokenKerberos


class ContextoFalso:
    """Imita gssapi.SecurityContext: 1o step gera o ticket; 2o valida a resposta do servidor."""

    def __init__(self, resposta_esperada=b"resposta-do-servidor"):
        self.resposta_esperada = resposta_esperada
        self.complete = False
        self.passos = []

    def step(self, token=None):
        self.passos.append(token)
        if token is None:
            return b"ticket-kerberos"
        if token != self.resposta_esperada:
            raise RuntimeError("GSS failure: servidor nao autenticado")
        self.complete = True
        return None


CABECALHO_OK = {"WWW-Authenticate": "Negotiate " + base64.b64encode(b"resposta-do-servidor").decode()}
CORPO_OK = {"id": "k1", "name": "enade-api-kerberos", "encoded": "chave-123",
            "expiration": int((time.time() + 3600) * 1000)}


def _provedor(corpo=CORPO_OK, cabecalhos=CABECALHO_OK, status=200, contexto=None):
    enviados = []
    ctx = contexto or ContextoFalso()

    async def post(url, json_corpo, headers):
        enviados.append((url, json_corpo, headers))
        return status, cabecalhos, corpo
    p = ProvedorTokenKerberos("http://elasticsearch:9200/", "HTTP@elasticsearch", "api@ENADE.LOCAL",
                              "/keytabs/api.keytab", http_post=post, fabrica_contexto=lambda: ctx)
    return p, enviados, ctx


def test_autenticacao_mutua_sucesso():
    p, enviados, ctx = _provedor()
    chave = asyncio.run(p.obter_token())
    assert chave == "chave-123"
    url, corpo, headers = enviados[0]
    assert url == "http://elasticsearch:9200/_security/api_key"
    assert corpo["expiration"] == "1h"
    assert headers["Authorization"] == "Negotiate " + base64.b64encode(b"ticket-kerberos").decode()
    assert ctx.complete and ctx.passos[1] == b"resposta-do-servidor"  # cliente validou o servidor
    assert p.expira_em > time.time() + 3000


def test_token_reutilizado_ate_expirar():
    p, enviados, _ = _provedor()
    asyncio.run(p.obter_token())
    asyncio.run(p.obter_token())
    assert len(enviados) == 1
    p.expira_em = 0
    assert p.expirado()
    asyncio.run(p.obter_token())
    assert len(enviados) == 2


def test_servidor_impostor_e_rejeitado():
    falso = {"WWW-Authenticate": "Negotiate " + base64.b64encode(b"forjado").decode()}
    p, _, _ = _provedor(cabecalhos=falso)
    with pytest.raises(FalhaAutenticacaoMutua):
        asyncio.run(p.obter_token())
    assert p.token is None


def test_servidor_sem_token_de_resposta_e_rejeitado():
    p, _, _ = _provedor(cabecalhos={})
    with pytest.raises(FalhaAutenticacaoMutua):
        asyncio.run(p.obter_token())
    assert p.token is None


def test_ticket_recusado_pelo_elasticsearch():
    p, _, _ = _provedor(corpo={"error": {"type": "security_exception"}}, status=401)
    with pytest.raises(FalhaAutenticacaoMutua):
        asyncio.run(p.obter_token())


def test_configuracao_kafka_gssapi():
    """O pipeline usa SASL/GSSAPI no Kafka quando KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT."""
    import importlib
    import os
    import sys
    raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ingestao"))
    sys.path.insert(0, raiz)
    try:
        os.environ.update({"KAFKA_SECURITY_PROTOCOL": "SASL_PLAINTEXT", "KAFKA_KERBEROS_PRINCIPAL": "consumidor@ENADE.LOCAL",
                           "KAFKA_KERBEROS_KEYTAB": "/keytabs/consumidor.keytab"})
        from enade import config
        importlib.reload(config)
        assert config.kafka_seguranca() == {
            "security.protocol": "SASL_PLAINTEXT", "sasl.mechanisms": "GSSAPI",
            "sasl.kerberos.service.name": "kafka", "sasl.kerberos.principal": "consumidor@ENADE.LOCAL",
            "sasl.kerberos.keytab": "/keytabs/consumidor.keytab"}
        os.environ["KAFKA_SECURITY_PROTOCOL"] = "PLAINTEXT"
        importlib.reload(config)
        assert config.kafka_seguranca() == {}
    finally:
        for k in ("KAFKA_SECURITY_PROTOCOL", "KAFKA_KERBEROS_PRINCIPAL", "KAFKA_KERBEROS_KEYTAB"):
            os.environ.pop(k, None)
        importlib.reload(config)
        sys.path.remove(raiz)
