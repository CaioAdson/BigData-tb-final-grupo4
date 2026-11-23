"""Testes de integracao com servicos REAIS (Elasticsearch, Redis e OpenLDAP).

Rodam so quando as variaveis abaixo existem (veja README, secao "Testes"):
  ES_TEST_URL     ex.: http://localhost:19200   (indice temporario e criado e apagado)
  REDIS_TEST_URL  ex.: redis://:senha@localhost:16379/15
  LDAP_TEST_URL   ex.: ldap://localhost:13389 + LDAP_TEST_BIND_DN/PASSWORD e senhas demo

O indice usa a MESMA definicao do pipeline (ingestao/enade/indice.py): analisador PT-BR
com stemming, stopwords, asciifolding e sinonimos. Assim validamos a relevancia real.
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.dependencias import Estado
from app.main import criar_app
from app.seguranca.ldap import AutenticadorLDAP, CredenciaisInvalidas
from app.seguranca.sessoes import GerenciadorSessoes
from app.servicos.cache import CacheConsultas
from app.servicos.carrinho import Carrinho

from .fakes import QUESTOES

pytestmark = pytest.mark.integracao
ES_URL = os.getenv("ES_TEST_URL")
REDIS_URL = os.getenv("REDIS_TEST_URL")
LDAP_URL = os.getenv("LDAP_TEST_URL")
INDICE = "enade-teste-api"

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestao"))


def _criar_indice():
    from elasticsearch import Elasticsearch
    from enade import indice, modelos
    es = Elasticsearch(ES_URL)
    if es.indices.exists(index=INDICE):
        es.indices.delete(index=INDICE)
    d = indice.definicao()
    d["settings"]["number_of_shards"] = 1
    es.indices.create(index=INDICE, settings=d["settings"], mappings=d["mappings"])
    for q in QUESTOES:
        doc = {**q, "texto_completo": modelos.montar_texto_completo(q),
               "origem": {"pdf": "teste.pdf", "pagina_inicio": 1}}
        es.index(index=INDICE, id=q["id"], document=doc)
    es.indices.refresh(index=INDICE)
    return es


@pytest.fixture(scope="module")
def indice_real():
    if not ES_URL:
        pytest.skip("ES_TEST_URL nao definido")
    es = _criar_indice()
    yield
    es.indices.delete(index=INDICE)
    es.close()


@pytest.fixture
def cliente_real(indice_real):
    import redis.asyncio as redis
    from elasticsearch import AsyncElasticsearch
    from fakeredis import FakeAsyncRedis
    from ldap3 import MOCK_SYNC

    from .fakes import BASE, servidor_ldap_mock
    cfg = Config(es_url=ES_URL, es_index=INDICE, ldap_bind_dn=f"cn=admin,{BASE}", ldap_bind_password="admin-teste")
    r = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else FakeAsyncRedis(decode_responses=True)
    estado = Estado(cfg=cfg, es=AsyncElasticsearch(ES_URL), redis=r,
                    cache=CacheConsultas(r, cfg.cache_ttl), sessoes=GerenciadorSessoes(r, cfg.sessao_ttl),
                    carrinho=Carrinho(r, cfg.sessao_ttl, cfg.carrinho_max),
                    autenticador=AutenticadorLDAP(cfg, servidor=servidor_ldap_mock(), estrategia=MOCK_SYNC))
    with TestClient(criar_app(estado)) as c:
        if REDIS_URL:
            c.portal.call(r.flushdb)
        yield c
        if REDIS_URL:
            c.portal.call(r.flushdb)
        c.portal.call(estado.es.close)


def _ids(resposta):
    return [q["id"] for q in resposta.json()["questoes"]]


def test_stemming_portugues(cliente_real):
    # 'algoritmo' (singular) encontra 'algoritmos' e 'algoritmo'; sem acento encontra com acento
    assert set(_ids(cliente_real.get("/api/questoes", params={"q": "algoritmo"}))) == {
        "si-2021-ce-009", "si-2023-ce-010", "cc-2023-ce-011"}
    assert "enf-2022-fg-002" in _ids(cliente_real.get("/api/questoes", params={"q": "politicas publicas"}))


def test_sinonimos(cliente_real):
    # ingestao/mapping/sinonimos.txt: "etica, moral, deontologia"
    assert "si-2021-fg-001" in _ids(cliente_real.get("/api/questoes", params={"q": "deontologia"}))


def test_relevancia_enunciado_primeiro(cliente_real):
    ids = _ids(cliente_real.get("/api/questoes", params={"q": "algoritmos de ordenação"}))
    assert ids[0] == "si-2021-ce-009"


def test_destaque_real(cliente_real):
    q = cliente_real.get("/api/questoes", params={"q": "ordenação"}).json()["questoes"][0]
    assert any("<mark>ordenação</mark>" in t for t in q["destaques"]["enunciado"])


def test_filtros_combinados_reais(cliente_real):
    r = cliente_real.get("/api/questoes", params={"q": "algoritmos", "ano": 2023, "tipo_questao": "discursiva",
                                                  "curso": "Ciência da Computação", "competencia": "Raciocínio lógico"})
    assert _ids(r) == ["cc-2023-ce-011"]
    assert cliente_real.get("/api/questoes", params={"tipo_prova": "FG", "area": "Saúde"}).json()["total"] == 1


def test_paginacao_real(cliente_real):
    vistos = []
    for p in (1, 2, 3):
        vistos += _ids(cliente_real.get("/api/questoes", params={"pagina": p, "tamanho": 2}))
    assert len(vistos) == len(set(vistos)) == 5


def test_estatisticas_reais(cliente_real):
    e = cliente_real.get("/api/estatisticas").json()
    assert e["total_questoes"] == 5
    assert {"nome": "Componente Específico", "quantidade": 3} in e["por_tipo_prova"]
    hist = {c["competencia"]: c["por_ano"] for c in e["competencias_por_ano"]}
    assert hist["Algoritmos"] == [{"ano": 2021, "quantidade": 1}, {"ano": 2023, "quantidade": 1}]
    filtros = {f["parametro"]: f for f in cliente_real.get("/api/questoes/filtros").json()["filtros"]}
    assert filtros["curso"]["valores"] == ["Ciência da Computação", "Enfermagem", "Sistemas de Informação"]


def test_cache_redis_real(cliente_real):
    a = cliente_real.get("/api/questoes", params={"q": "saúde"})
    b = cliente_real.get("/api/questoes", params={"q": "saúde"})
    assert (a.headers["X-Cache"], b.headers["X-Cache"]) == ("MISS", "HIT") and a.json() == b.json()


def test_detalhe_real(cliente_real):
    assert cliente_real.get("/api/questoes/si-2021-fg-001").json()["texto_base"].startswith("A ética")
    assert cliente_real.get("/api/questoes/nao-existe").status_code == 404


# ------------------------------------------------------------------ LDAP real
@pytest.fixture
def ldap_real():
    if not LDAP_URL:
        pytest.skip("LDAP_TEST_URL nao definido")
    cfg = Config(ldap_url=LDAP_URL, ldap_bind_dn=os.getenv("LDAP_TEST_BIND_DN"),
                 ldap_bind_password=os.getenv("LDAP_TEST_BIND_PASSWORD"))
    return AutenticadorLDAP(cfg)


def test_ldap_real_perfis(ldap_real):
    prof = ldap_real.autenticar("prof.demo", os.environ["LDAP_TEST_SENHA_PROFESSOR"])
    aluno = ldap_real.autenticar("aluno.demo", os.environ["LDAP_TEST_SENHA_ESTUDANTE"])
    assert (prof.perfil, prof.nome) == ("professor", "Professor Demo")
    assert aluno.perfil == "estudante"


def test_ldap_real_senha_errada(ldap_real):
    with pytest.raises(CredenciaisInvalidas):
        ldap_real.autenticar("prof.demo", "senha-errada")
    with pytest.raises(CredenciaisInvalidas):
        ldap_real.autenticar("prof.demo", "")
