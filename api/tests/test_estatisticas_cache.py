"""Estatisticas, agregacoes, painel do professor e cache Redis (hit/miss, TTL, invalidacao, metricas)."""
import json

from app.schemas import Estatisticas, PainelProfessor
from app.servicos.cache import CacheConsultas

from .conftest import assert_erro


def test_estatisticas_contrato(cliente):
    corpo = cliente.get("/api/estatisticas").json()
    Estatisticas.model_validate(corpo)
    assert corpo["total_questoes"] == 5
    assert {"nome": "Computação", "quantidade": 4} in corpo["por_area"]
    assert corpo["por_ano"] == [{"nome": "2021", "quantidade": 2}, {"nome": "2022", "quantidade": 1},
                                {"nome": "2023", "quantidade": 2}]
    assert {"nome": "discursiva", "quantidade": 1} in corpo["por_tipo_questao"]
    assert {"nome": "Formação Geral", "quantidade": 2} in corpo["por_tipo_prova"]
    assert {"nome": "Sistemas de Informação", "quantidade": 3} in corpo["por_curso"]


def test_histograma_competencias_por_ano(cliente):
    corpo = cliente.get("/api/estatisticas").json()
    hist = {c["competencia"]: c for c in corpo["competencias_por_ano"]}
    assert hist["Algoritmos"]["total"] == 2
    assert hist["Algoritmos"]["por_ano"] == [{"ano": 2021, "quantidade": 1}, {"ano": 2023, "quantidade": 1}]
    assert hist["Raciocínio lógico"]["por_ano"] == [{"ano": 2021, "quantidade": 1}, {"ano": 2023, "quantidade": 1}]


def test_estatisticas_sem_indice_mantem_estrutura(cliente, es_fake):
    es_fake.indice_existe = False
    corpo = cliente.get("/api/estatisticas").json()
    assert corpo == {"total_questoes": 0, "por_area": [], "por_ano": [], "por_tipo_questao": [],
                     "por_tipo_prova": [], "por_curso": [], "competencias_por_ano": []}


def test_cache_hit_miss(cliente, es_fake):
    r1 = cliente.get("/api/questoes", params={"q": "ética"})
    r2 = cliente.get("/api/questoes", params={"q": "ética"})
    assert r1.headers["X-Cache"] == "MISS" and r2.headers["X-Cache"] == "HIT"
    assert r1.json() == r2.json()
    assert len(es_fake.chamadas) == 1  # segunda resposta nao foi ao Elasticsearch
    r3 = cliente.get("/api/questoes", params={"q": "ética", "pagina": 2})
    assert r3.headers["X-Cache"] == "MISS"


def test_cache_tem_ttl(cliente, redis_fake):
    cliente.get("/api/estatisticas")
    chaves = [k for k in _sync_keys(cliente, redis_fake, "enade:cache:v0:*")]
    assert chaves
    ttl = cliente.portal.call(redis_fake.ttl, chaves[0])
    assert 0 < ttl <= 300


def _sync_keys(cliente, redis, padrao):
    return cliente.portal.call(redis.keys, padrao)


def test_cache_respeita_perfil(cliente, professor, estudante):
    # Professor popula o cache; estudante recebe a MESMA entrada mas sem gabarito.
    rp = cliente.get("/api/questoes", params={"curso": "Enfermagem"}, headers=professor)
    re_ = cliente.get("/api/questoes", params={"curso": "Enfermagem"}, headers=estudante)
    assert re_.headers["X-Cache"] == "HIT"
    assert rp.json()["questoes"][0]["gabarito"] == "A"
    assert re_.json()["questoes"][0]["gabarito"] is None


def test_cache_inconsistente_e_descartado(cliente, redis_fake, es_fake):
    cliente.get("/api/questoes", params={"q": "saúde"})
    chave = _sync_keys(cliente, redis_fake, "enade:cache:v0:questoes:*")[0]
    cliente.portal.call(redis_fake.set, chave, json.dumps({"endpoint": "questoes", "parametros": {"q": "outra"}, "dados": {}}))
    r = cliente.get("/api/questoes", params={"q": "saúde"})
    assert r.headers["X-Cache"] == "MISS" and r.json()["total"] == 1


def test_redis_fora_nao_derruba_pesquisa(cliente, estado):
    class RedisQuebrado:
        def __getattr__(self, _):
            async def falha(*a, **k):
                raise ConnectionError("redis down")
            return falha

        def pipeline(self):
            raise ConnectionError("redis down")
    estado.cache = CacheConsultas(RedisQuebrado(), 300)
    r = cliente.get("/api/questoes", params={"q": "ética"})
    assert r.status_code == 200 and r.headers["X-Cache"] == "MISS"


def test_invalidacao_e_metricas(cliente, professor, es_fake):
    cliente.get("/api/questoes", params={"q": "ética"})          # miss
    cliente.get("/api/questoes", params={"q": "ética"})          # hit
    cliente.get("/api/questoes", params={"q": "ética"})          # hit
    m = cliente.get("/api/cache/metricas", headers=professor).json()
    assert m["hits"] == 2 and m["misses"] == 1 and m["hit_rate"] == round(2 / 3, 4)
    assert m["por_endpoint"]["questoes"] == {"hits": 2, "misses": 1, "erros": 0}
    assert m["chaves_ativas"] == 1 and m["ttl_segundos"] == 300 and m["versao"] == 0

    r = cliente.post("/api/cache/invalidar", headers=professor)
    assert r.status_code == 200 and r.json()["versao"] == 1
    antes = len(es_fake.chamadas)
    r = cliente.get("/api/questoes", params={"q": "ética"})
    assert r.headers["X-Cache"] == "MISS" and len(es_fake.chamadas) == antes + 1
    assert cliente.get("/api/cache/metricas", headers=professor).json()["chaves_ativas"] == 1


def test_painel_professor(cliente, professor):
    corpo = cliente.get("/api/painel/professor", headers=professor).json()
    PainelProfessor.model_validate(corpo)
    assert corpo["qualidade"]["anuladas"] == 1
    assert corpo["qualidade"]["sem_competencias"] == 1
    assert corpo["gabaritos_por_ano"] == [{"ano": 2021, "quantidade": 2}, {"ano": 2022, "quantidade": 1}]
    assert corpo["anuladas_por_ano"] == [{"ano": 2023, "quantidade": 1}]
    assert corpo["estatisticas"]["total_questoes"] == 5


def test_painel_e_cache_negados_para_estudante(cliente, estudante):
    assert_erro(cliente.get("/api/painel/professor", headers=estudante), 403, "ACESSO_NEGADO")
    assert_erro(cliente.get("/api/cache/metricas", headers=estudante), 403, "ACESSO_NEGADO")
    assert_erro(cliente.post("/api/cache/invalidar", headers=estudante), 403, "ACESSO_NEGADO")
    assert_erro(cliente.get("/api/painel/professor"), 401, "NAO_AUTENTICADO")
