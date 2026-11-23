"""Autenticacao LDAP, sessoes (expiracao), perfis e HTTP 403."""
import time

import pytest
from ldap3 import MOCK_SYNC

from app.schemas import Token
from app.seguranca.ldap import AutenticadorLDAP, CredenciaisInvalidas, LDAPIndisponivel, SemPerfil
from app.seguranca.sessoes import id_sessao

from .conftest import assert_erro
from .fakes import SENHAS, servidor_ldap_mock


# ------------------------------------------------------------ LDAP (unidade)
@pytest.fixture
def ldap(cfg):
    return AutenticadorLDAP(cfg, servidor=servidor_ldap_mock(), estrategia=MOCK_SYNC)


def test_ldap_professor(ldap):
    u = ldap.autenticar("prof.ana", SENHAS["prof.ana"])
    assert (u.id, u.nome, u.perfil) == ("prof.ana", "Ana Professora", "professor")
    assert u.dn == "uid=prof.ana,ou=usuarios,dc=enade,dc=local"


def test_ldap_estudante(ldap):
    assert ldap.autenticar("aluno.bruno", SENHAS["aluno.bruno"]).perfil == "estudante"


@pytest.mark.parametrize("usuario,senha", [
    ("prof.ana", "errada"), ("nao.existe", "x"), ("prof.ana", ""), ("", "x"),
    ("*", "x"), ("prof.ana)(uid=*", "x"),  # tentativa de LDAP injection
])
def test_ldap_credenciais_invalidas(ldap, usuario, senha):
    with pytest.raises(CredenciaisInvalidas):
        ldap.autenticar(usuario, senha)


def test_ldap_usuario_sem_grupo(ldap):
    with pytest.raises(SemPerfil):
        ldap.autenticar("visitante", SENHAS["visitante"])


def test_ldap_indisponivel(cfg):
    from ldap3 import Server
    cfg.ldap_timeout = 1
    autenticador = AutenticadorLDAP(cfg, servidor=Server("ldap://127.0.0.1:1", connect_timeout=1))
    with pytest.raises(LDAPIndisponivel):
        autenticador.autenticar("prof.ana", "x")


# ------------------------------------------------------------ login (HTTP)
def test_login_professor_contrato(cliente):
    r = cliente.post("/api/auth/login", json={"usuario": "prof.ana", "senha": SENHAS["prof.ana"]})
    assert r.status_code == 200
    corpo = Token.model_validate(r.json())
    assert corpo.token_type == "bearer" and len(corpo.access_token) >= 40
    assert corpo.usuario.perfil == "professor" and "ver_gabarito" in corpo.usuario.permissoes
    me = cliente.get("/api/auth/me", headers={"Authorization": f"Bearer {corpo.access_token}"}).json()
    assert me["id"] == "prof.ana" and me["perfil"] == "professor"


def test_login_estudante(cliente):
    r = cliente.post("/api/auth/login", json={"usuario": "aluno.bruno", "senha": SENHAS["aluno.bruno"]})
    assert r.json()["usuario"]["perfil"] == "estudante"
    assert "ver_gabarito" not in r.json()["usuario"]["permissoes"]


def test_login_invalido(cliente):
    assert_erro(cliente.post("/api/auth/login", json={"usuario": "prof.ana", "senha": "errada"}), 401, "CREDENCIAIS_INVALIDAS")
    assert_erro(cliente.post("/api/auth/login", json={"usuario": "visitante", "senha": SENHAS["visitante"]}), 403, "USUARIO_SEM_PERFIL")
    assert_erro(cliente.post("/api/auth/login", json={"usuario": "prof.ana"}), 400, "PARAMETROS_INVALIDOS")


def test_login_bloqueado_apos_falhas(cliente):
    for _ in range(3):
        cliente.post("/api/auth/login", json={"usuario": "aluno.bruno", "senha": "errada"})
    r = cliente.post("/api/auth/login", json={"usuario": "aluno.bruno", "senha": SENHAS["aluno.bruno"]})
    assert_erro(r, 429, "LOGIN_BLOQUEADO")


def test_token_guardado_como_hash(cliente, redis_fake, professor):
    token = professor["Authorization"].split()[1]
    chaves = cliente.portal.call(redis_fake.keys, "enade:sessao:*")
    assert chaves == [f"enade:sessao:{id_sessao(token)}"]
    assert token not in chaves[0]


def test_me_sem_token(cliente):
    r = cliente.get("/api/auth/me")
    assert_erro(r, 401, "NAO_AUTENTICADO")
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_logout_invalida_sessao(cliente, professor):
    assert cliente.post("/api/auth/logout", headers=professor).status_code == 204
    assert_erro(cliente.get("/api/auth/me", headers=professor), 401, "SESSAO_EXPIRADA")


def test_sessao_expira(cliente, estado, redis_fake):
    estado.sessoes.ttl = 1
    r = cliente.post("/api/auth/login", json={"usuario": "aluno.bruno", "senha": SENHAS["aluno.bruno"]})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert cliente.get("/api/auth/me", headers=headers).status_code == 200
    time.sleep(1.2)
    assert_erro(cliente.get("/api/auth/me", headers=headers), 401, "SESSAO_EXPIRADA")


def test_sessao_renovada_a_cada_uso(cliente, estado, redis_fake, professor):
    token = professor["Authorization"].split()[1]
    chave = f"enade:sessao:{id_sessao(token)}"
    cliente.portal.call(redis_fake.expire, chave, 10)
    cliente.get("/api/auth/me", headers=professor)
    assert cliente.portal.call(redis_fake.ttl, chave) > 3000


def test_login_ldap_fora_retorna_503(cliente, estado):
    def falha(*_):
        raise LDAPIndisponivel()
    estado.autenticador.autenticar = falha
    assert_erro(cliente.post("/api/auth/login", json={"usuario": "a", "senha": "b"}), 503, "SERVICO_INDISPONIVEL")


# ------------------------------------------------------------ permissoes (matriz)
ROTAS_PROFESSOR = [
    ("get", "/api/painel/professor", {}),
    ("get", "/api/cache/metricas", {}),
    ("post", "/api/cache/invalidar", {}),
    ("get", "/api/carrinho/exportar", {"params": {"formato": "json", "incluir_gabarito": "true"}}),
    ("get", "/api/carrinho/exportar", {"params": {"formato": "pdf", "incluir_gabarito": "true"}}),
]


@pytest.mark.parametrize("metodo,rota,extra", ROTAS_PROFESSOR)
def test_estudante_recebe_403(cliente, estudante, metodo, rota, extra):
    r = getattr(cliente, metodo)(rota, headers=estudante, **extra)
    assert_erro(r, 403, "ACESSO_NEGADO")


@pytest.mark.parametrize("metodo,rota,extra", ROTAS_PROFESSOR)
def test_anonimo_recebe_401(cliente, metodo, rota, extra):
    assert_erro(getattr(cliente, metodo)(rota, **extra), 401, "NAO_AUTENTICADO")


@pytest.mark.parametrize("metodo,rota,extra", ROTAS_PROFESSOR[:3])
def test_professor_acessa(cliente, professor, metodo, rota, extra):
    assert getattr(cliente, metodo)(rota, headers=professor, **extra).status_code == 200


def test_estudante_pode_pesquisar_e_filtrar(cliente, estudante):
    assert cliente.get("/api/questoes", params={"q": "algoritmos", "ano": 2021}, headers=estudante).status_code == 200
    assert cliente.get("/api/estatisticas", headers=estudante).status_code == 200
    assert cliente.get("/api/questoes/filtros", headers=estudante).status_code == 200
