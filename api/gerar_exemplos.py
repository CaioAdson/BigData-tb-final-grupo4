"""Gera api/exemplos/*.json chamando a API de verdade com dados ficticios (tests/fakes.py).

Como as respostas saem do proprio codigo da API, os exemplos seguem EXATAMENTE o contrato.
O teste tests/test_exemplos.py falha se algum exemplo deixar de validar contra os schemas.
Uso: cd api && python gerar_exemplos.py
"""
import json
from pathlib import Path

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
from tests.fakes import BASE, SENHAS, FakeES, servidor_ldap_mock

DESTINO = Path(__file__).parent / "exemplos"


def gerar() -> dict[str, object]:
    cfg = Config(ldap_bind_dn=f"cn=admin,{BASE}", ldap_bind_password="admin-teste")
    r = FakeAsyncRedis(decode_responses=True)
    estado = Estado(cfg=cfg, es=FakeES(), redis=r, cache=CacheConsultas(r, cfg.cache_ttl),
                    sessoes=GerenciadorSessoes(r, cfg.sessao_ttl), carrinho=Carrinho(r, cfg.sessao_ttl, cfg.carrinho_max),
                    autenticador=AutenticadorLDAP(cfg, servidor=servidor_ldap_mock(), estrategia=MOCK_SYNC))
    ex = {}
    with TestClient(criar_app(estado)) as c:
        def login(u):
            corpo = c.post("/api/auth/login", json={"usuario": u, "senha": SENHAS[u]}).json()
            return corpo, {"Authorization": f"Bearer {corpo['access_token']}"}
        login_prof, prof = login("prof.ana")
        login_aluno, aluno = login("aluno.bruno")
        for corpo in (login_prof, login_aluno):
            corpo["access_token"] = "token_exemplo"
        ex["auth_login_professor"] = login_prof
        ex["auth_login_estudante"] = login_aluno
        ex["auth_me"] = c.get("/api/auth/me", headers=aluno).json()
        ex["questoes_pesquisa"] = c.get("/api/questoes", params={"q": "algoritmos", "area": "Computação", "pagina": 1, "tamanho": 10}).json()
        ex["questoes_pesquisa_professor"] = c.get("/api/questoes", params={"q": "algoritmos", "ano": 2021}, headers=prof).json()
        ex["questoes_vazia"] = c.get("/api/questoes", params={"q": "astrofísica"}).json()
        ex["questoes_filtros"] = c.get("/api/questoes/filtros").json()
        ex["questao_detalhe"] = c.get("/api/questoes/si-2021-fg-001").json()
        ex["estatisticas"] = c.get("/api/estatisticas").json()
        c.post("/api/carrinho/questoes", json={"id": "si-2021-fg-001"}, headers=prof)
        ex["carrinho"] = c.post("/api/carrinho/questoes", json={"id": "si-2021-ce-009"}, headers=prof).json()
        simulado = c.get("/api/carrinho/exportar", params={"formato": "json"}, headers=prof).json()
        simulado["gerado_em"] = "2026-11-23T12:00:00+00:00"
        ex["simulado_exportado"] = simulado
        ex["painel_professor"] = c.get("/api/painel/professor", headers=prof).json()
        ex["cache_metricas"] = c.get("/api/cache/metricas", headers=prof).json()
        ex["erros"] = {
            "400_parametros_invalidos": c.get("/api/questoes", params={"tamanho": 500}).json(),
            "401_nao_autenticado": c.get("/api/carrinho").json(),
            "401_credenciais_invalidas": c.post("/api/auth/login", json={"usuario": "prof.ana", "senha": "x"}).json(),
            "403_acesso_negado": c.get("/api/painel/professor", headers=aluno).json(),
            "404_questao_nao_encontrada": c.get("/api/questoes/nao-existe").json(),
            "503_servico_indisponivel": {"erro": {"codigo": "SERVICO_INDISPONIVEL",
                                                  "mensagem": "Servico Elasticsearch indisponivel no momento. Tente novamente."}},
        }
    return ex


if __name__ == "__main__":
    DESTINO.mkdir(exist_ok=True)
    for nome, dados in gerar().items():
        (DESTINO / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("gerado", nome)
