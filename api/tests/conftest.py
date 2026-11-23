import pytest
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient
from ldap3 import MOCK_SYNC

from app.config import Config
from app.dependencias import Estado
from app.main import criar_app
from app.seguranca.ldap import AutenticadorLDAP
from app.seguranca.sessoes import GerenciadorSessoes
from app.servicos.cache import CacheConsultas
from app.servicos.carrinho import Carrinho

from .fakes import BASE, SENHAS, FakeES, servidor_ldap_mock


@pytest.fixture
def cfg():
    return Config(ldap_bind_dn=f"cn=admin,{BASE}", ldap_bind_password="admin-teste",
                  cache_ttl=300, sessao_ttl=3600, carrinho_max=3, login_max_falhas=3)


@pytest.fixture
def redis_fake():
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def es_fake():
    return FakeES()


@pytest.fixture
def estado(cfg, redis_fake, es_fake):
    return Estado(
        cfg=cfg, es=es_fake, redis=redis_fake,
        cache=CacheConsultas(redis_fake, cfg.cache_ttl),
        sessoes=GerenciadorSessoes(redis_fake, cfg.sessao_ttl),
        carrinho=Carrinho(redis_fake, cfg.sessao_ttl, cfg.carrinho_max),
        autenticador=AutenticadorLDAP(cfg, servidor=servidor_ldap_mock(), estrategia=MOCK_SYNC),
    )


@pytest.fixture
def cliente(estado):
    with TestClient(criar_app(estado)) as c:
        yield c


def _login(cliente, usuario):
    r = cliente.post("/api/auth/login", json={"usuario": usuario, "senha": SENHAS[usuario]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def professor(cliente):
    return _login(cliente, "prof.ana")


@pytest.fixture
def estudante(cliente):
    return _login(cliente, "aluno.bruno")


def assert_erro(resposta, status, codigo=None):
    assert resposta.status_code == status, resposta.text
    corpo = resposta.json()
    assert set(corpo) == {"erro"}
    assert isinstance(corpo["erro"]["codigo"], str) and corpo["erro"]["codigo"].isupper()
    assert isinstance(corpo["erro"]["mensagem"], str) and corpo["erro"]["mensagem"]
    if codigo:
        assert corpo["erro"]["codigo"] == codigo
    return corpo
