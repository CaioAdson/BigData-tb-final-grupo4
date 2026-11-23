"""Carrinho no Redis (adicao, remocao, limpeza, expiracao) e exportacao PDF/JSON."""
import io
import json
import time

from pypdf import PdfReader

from app.schemas import Carrinho
from app.seguranca.sessoes import chave_carrinho, id_sessao

from .conftest import assert_erro


def _add(cliente, headers, qid):
    return cliente.post("/api/carrinho/questoes", json={"id": qid}, headers=headers)


def test_carrinho_exige_login(cliente):
    assert_erro(cliente.get("/api/carrinho"), 401, "NAO_AUTENTICADO")
    assert_erro(cliente.post("/api/carrinho/questoes", json={"id": "x"}), 401)


def test_adicionar_listar_remover_limpar(cliente, estudante):
    assert cliente.get("/api/carrinho", headers=estudante).json()["total"] == 0
    r = _add(cliente, estudante, "si-2021-ce-009")
    assert r.status_code == 201
    r = _add(cliente, estudante, "enf-2022-fg-002")
    corpo = Carrinho.model_validate(r.json())
    assert [q.id for q in corpo.questoes] == ["si-2021-ce-009", "enf-2022-fg-002"]  # ordem de inclusao
    assert all(q.gabarito is None for q in corpo.questoes)  # estudante
    assert 0 < corpo.expira_em <= 3600

    r = _add(cliente, estudante, "si-2021-ce-009")  # duplicada: idempotente
    assert r.status_code == 200 and r.json()["total"] == 2

    r = cliente.delete("/api/carrinho/questoes/si-2021-ce-009", headers=estudante)
    assert r.status_code == 200 and [q["id"] for q in r.json()["questoes"]] == ["enf-2022-fg-002"]
    assert_erro(cliente.delete("/api/carrinho/questoes/si-2021-ce-009", headers=estudante), 404, "QUESTAO_NAO_ESTA_NO_CARRINHO")

    assert cliente.delete("/api/carrinho", headers=estudante).status_code == 204
    assert cliente.get("/api/carrinho", headers=estudante).json()["total"] == 0


def test_professor_ve_gabarito_no_carrinho(cliente, professor):
    r = _add(cliente, professor, "enf-2022-fg-002")
    assert r.json()["questoes"][0]["gabarito"] == "A"


def test_questao_inexistente(cliente, estudante):
    assert_erro(_add(cliente, estudante, "nao-existe"), 404, "QUESTAO_NAO_ENCONTRADA")
    assert_erro(cliente.post("/api/carrinho/questoes", json={}, headers=estudante), 400, "PARAMETROS_INVALIDOS")


def test_limite_do_carrinho(cliente, estudante):
    for qid in ["si-2021-fg-001", "si-2021-ce-009", "si-2023-ce-010"]:
        assert _add(cliente, estudante, qid).status_code == 201
    assert_erro(_add(cliente, estudante, "enf-2022-fg-002"), 409, "CARRINHO_CHEIO")


def test_carrinhos_isolados_por_sessao(cliente, estudante, professor):
    _add(cliente, estudante, "si-2021-fg-001")
    assert cliente.get("/api/carrinho", headers=professor).json()["total"] == 0


def test_carrinho_persistido_no_redis_com_ttl(cliente, redis_fake, estudante):
    _add(cliente, estudante, "si-2021-fg-001")
    chave = chave_carrinho(id_sessao(estudante["Authorization"].split()[1]))
    assert cliente.portal.call(redis_fake.zrange, chave, 0, -1) == ["si-2021-fg-001"]
    assert 0 < cliente.portal.call(redis_fake.ttl, chave) <= 3600


def test_carrinho_expira_com_a_sessao(cliente, estado, redis_fake):
    from .fakes import SENHAS
    estado.sessoes.ttl = 1
    estado.carrinho.ttl = 1
    token = cliente.post("/api/auth/login", json={"usuario": "aluno.bruno", "senha": SENHAS["aluno.bruno"]}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    _add(cliente, h, "si-2021-fg-001")
    time.sleep(1.2)
    assert cliente.portal.call(redis_fake.exists, chave_carrinho(id_sessao(token))) == 0
    assert_erro(cliente.get("/api/carrinho", headers=h), 401, "SESSAO_EXPIRADA")


def test_logout_apaga_carrinho(cliente, redis_fake, estudante):
    _add(cliente, estudante, "si-2021-fg-001")
    cliente.post("/api/auth/logout", headers=estudante)
    chave = chave_carrinho(id_sessao(estudante["Authorization"].split()[1]))
    assert cliente.portal.call(redis_fake.exists, chave) == 0


# ------------------------------------------------------------ exportacao
def test_exportar_carrinho_vazio(cliente, professor):
    assert_erro(cliente.get("/api/carrinho/exportar", params={"formato": "json"}, headers=professor), 400, "CARRINHO_VAZIO")


def test_exportar_json_professor_com_gabarito(cliente, professor):
    for qid in ["si-2021-fg-001", "cc-2023-ce-011"]:
        _add(cliente, professor, qid)
    r = cliente.get("/api/carrinho/exportar", params={"formato": "json"}, headers=professor)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers["content-disposition"]
    sim = json.loads(r.content)
    assert sim["inclui_gabarito"] is True and sim["total_questoes"] == 2
    q1 = sim["questoes"][0]
    assert q1["ordem"] == 1 and q1["texto_base"] == "A ética profissional orienta condutas."
    assert q1["alternativas"] == [{"letra": "A", "texto": "Moral é individual."}, {"letra": "B", "texto": "Ética é coletiva."}]
    assert q1["competencias"] == ["Ética"] and q1["curso"] == "Sistemas de Informação" and q1["ano"] == 2021
    assert sim["gabarito"][0] == {"ordem": 1, "id": "si-2021-fg-001", "gabarito": "B", "anulada": False}


def test_exportar_json_professor_sem_gabarito(cliente, professor):
    _add(cliente, professor, "si-2021-fg-001")
    sim = cliente.get("/api/carrinho/exportar", params={"formato": "json", "incluir_gabarito": "false"}, headers=professor).json()
    assert sim["inclui_gabarito"] is False and sim["gabarito"] is None and sim["questoes"][0]["gabarito"] is None


def test_exportar_estudante_sem_gabarito(cliente, estudante):
    _add(cliente, estudante, "si-2021-fg-001")
    sim = cliente.get("/api/carrinho/exportar", params={"formato": "json"}, headers=estudante).json()
    assert sim["inclui_gabarito"] is False and sim["questoes"][0]["gabarito"] is None
    assert_erro(cliente.get("/api/carrinho/exportar", params={"formato": "json", "incluir_gabarito": "true"},
                            headers=estudante), 403, "ACESSO_NEGADO")


def _texto_pdf(conteudo: bytes) -> str:
    leitor = PdfReader(io.BytesIO(conteudo))
    return "\n".join(p.extract_text() for p in leitor.pages)


def test_exportar_pdf_professor(cliente, professor):
    for qid in ["si-2021-fg-001", "cc-2023-ce-011"]:
        _add(cliente, professor, qid)
    r = cliente.get("/api/carrinho/exportar", params={"formato": "pdf"}, headers=professor)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    texto = _texto_pdf(r.content)
    assert "Sobre ética e cidadania" in texto
    assert "Moral é individual." in texto and "Ética é coletiva." in texto
    assert "Sistemas de Informação" in texto and "ENADE 2021" in texto and "Competências: Ética" in texto
    assert "Descreva a complexidade" in texto
    assert "Gabarito" in texto


def test_exportar_pdf_estudante_sem_gabarito(cliente, estudante):
    _add(cliente, estudante, "si-2021-fg-001")
    r = cliente.get("/api/carrinho/exportar", params={"formato": "pdf"}, headers=estudante)
    texto = _texto_pdf(r.content)
    assert "Sobre ética e cidadania" in texto and "Gabarito" not in texto


def test_exportar_formato_invalido(cliente, professor):
    assert_erro(cliente.get("/api/carrinho/exportar", params={"formato": "docx"}, headers=professor), 400, "PARAMETROS_INVALIDOS")
