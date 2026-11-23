"""Pesquisa textual, filtros combinados, paginacao, destaque e contrato de /api/questoes."""
from elasticsearch import ConnectionError as ESConnectionError

from app.schemas import Questao, RespostaQuestoes
from app.servicos import busca

from .conftest import assert_erro

CAMPOS_CONTRATO = {"id", "ano", "area", "curso", "tipo_prova", "tipo_questao", "numero", "enunciado",
                   "alternativas", "gabarito", "anulada", "competencias"}


def test_rotas_existentes_continuam(cliente):
    assert cliente.get("/").json()["status"] == "online"
    saude = cliente.get("/api/health").json()
    assert saude["api"] == "online" and saude["elasticsearch"] == "online" and saude["redis"] == "online"


def test_contrato_resposta(cliente):
    r = cliente.get("/api/questoes")
    assert r.status_code == 200
    corpo = r.json()
    RespostaQuestoes.model_validate(corpo)
    assert {"total", "pagina", "tamanho", "questoes"} <= set(corpo)
    assert corpo["total"] == 5
    for q in corpo["questoes"]:
        assert CAMPOS_CONTRATO <= set(q)
        assert isinstance(q["alternativas"], list) and isinstance(q["competencias"], list)
        assert q["tipo_prova"] in {"Formação Geral", "Componente Específico"}
        assert "qualidade" not in q and "texto_completo" not in q  # estrutura interna nao vaza


def test_pesquisa_textual_e_destaque(cliente, es_fake):
    r = cliente.get("/api/questoes", params={"q": "algoritmos"})
    corpo = r.json()
    ids = {q["id"] for q in corpo["questoes"]}
    assert ids == {"si-2021-ce-009", "si-2023-ce-010", "cc-2023-ce-011"}
    for q in corpo["questoes"]:
        assert any("<mark>" in t for trechos in q["destaques"].values() for t in trechos)
    consulta = es_fake.chamadas[-1]
    assert consulta["highlight"]["pre_tags"] == ["<mark>"]
    mm = consulta["query"]["bool"]["must"][0]["multi_match"]
    assert mm["query"] == "algoritmos" and "enunciado^3" in mm["fields"]


def test_sem_q_nao_ha_destaques(cliente, es_fake):
    corpo = cliente.get("/api/questoes").json()
    assert all(q["destaques"] == {} for q in corpo["questoes"])
    assert es_fake.chamadas[-1]["highlight"] is None


def test_filtros_combinados(cliente, es_fake):
    r = cliente.get("/api/questoes", params={
        "q": "algoritmos", "area": "Computação", "curso": "Sistemas de Informação", "ano": 2021,
        "tipo_prova": "Componente Específico", "tipo_questao": "objetiva", "competencia": "Algoritmos"})
    corpo = r.json()
    assert [q["id"] for q in corpo["questoes"]] == ["si-2021-ce-009"]
    filtros = es_fake.chamadas[-1]["query"]["bool"]["filter"]
    assert {"term": {"tipo_prova": "CE"}} in filtros
    assert {"term": {"competencias": "Algoritmos"}} in filtros
    assert len(filtros) == 6


def test_filtro_por_curso_e_competencia_isolados(cliente):
    assert cliente.get("/api/questoes", params={"curso": "Enfermagem"}).json()["total"] == 1
    assert cliente.get("/api/questoes", params={"competencia": "Raciocínio lógico"}).json()["total"] == 2


def test_tipo_prova_aceita_sigla_e_nome(cliente):
    a = cliente.get("/api/questoes", params={"tipo_prova": "FG"}).json()
    b = cliente.get("/api/questoes", params={"tipo_prova": "formacao geral"}).json()
    assert a["total"] == b["total"] == 2


def test_paginacao(cliente, es_fake):
    p1 = cliente.get("/api/questoes", params={"pagina": 1, "tamanho": 2}).json()
    p3 = cliente.get("/api/questoes", params={"pagina": 3, "tamanho": 2}).json()
    assert p1["total"] == 5 and p1["total_paginas"] == 3 and len(p1["questoes"]) == 2
    assert len(p3["questoes"]) == 1
    assert es_fake.chamadas[-1]["from_"] == 4
    ids = {q["id"] for q in p1["questoes"]} | {q["id"] for q in p3["questoes"]}
    assert len(ids) == 3


def test_sem_resultados_retorna_lista_vazia(cliente):
    corpo = cliente.get("/api/questoes", params={"q": "astrofisica quantica"}).json()
    assert corpo["total"] == 0 and corpo["questoes"] == [] and corpo["total_paginas"] == 0


def test_validacao_parametros(cliente):
    for params in ({"tamanho": 0}, {"tamanho": 101}, {"pagina": 0}, {"ano": "abc"}, {"ano": 1990},
                   {"tipo_questao": "multipla"}, {"tipo_prova": "XX"}, {"pagina": 200, "tamanho": 100},
                   {"q": "x" * 301}):
        corpo = assert_erro(cliente.get("/api/questoes", params=params), 400, "PARAMETROS_INVALIDOS")
        assert corpo["erro"]["detalhes"][0]["campo"]


def test_gabarito_oculto_para_anonimo_e_estudante(cliente, estudante, professor):
    def gabarito(headers=None):
        qs = cliente.get("/api/questoes", params={"curso": "Enfermagem"}, headers=headers).json()["questoes"]
        return qs[0]["gabarito"]
    assert gabarito() is None
    assert gabarito(estudante) is None
    assert gabarito(professor) == "A"


def test_detalhe_questao(cliente, professor):
    r = cliente.get("/api/questoes/si-2021-fg-001", headers=professor)
    assert r.status_code == 200
    q = r.json()
    Questao.model_validate(q)
    assert q["gabarito"] == "B" and q["texto_base"].startswith("A ética")
    assert cliente.get("/api/questoes/si-2021-fg-001").json()["gabarito"] is None
    assert_erro(cliente.get("/api/questoes/nao-existe"), 404, "QUESTAO_NAO_ENCONTRADA")


def test_token_invalido_retorna_401(cliente):
    assert_erro(cliente.get("/api/questoes", headers={"Authorization": "Bearer invalido"}), 401, "SESSAO_EXPIRADA")


def test_elasticsearch_fora_retorna_503(cliente, es_fake):
    es_fake.falhar = ESConnectionError("down")
    assert_erro(cliente.get("/api/questoes", params={"q": "nada-em-cache"}), 503, "SERVICO_INDISPONIVEL")
    assert cliente.get("/api/health").json()["elasticsearch"] == "offline"


def test_indice_inexistente_mantem_estrutura(cliente, es_fake):
    es_fake.indice_existe = False
    corpo = cliente.get("/api/questoes", params={"q": "x"}).json()
    assert corpo["total"] == 0 and corpo["questoes"] == []


def test_rota_inexistente_padrao_erro(cliente):
    assert_erro(cliente.get("/api/nao-existe"), 404, "RECURSO_NAO_ENCONTRADO")


def test_filtros_disponiveis(cliente):
    corpo = cliente.get("/api/questoes/filtros").json()
    por_nome = {f["parametro"]: f for f in corpo["filtros"]}
    assert set(por_nome) == {"q", "area", "curso", "ano", "tipo_prova", "tipo_questao", "competencia", "pagina", "tamanho"}
    assert all(f["implementado"] for f in corpo["filtros"])
    assert por_nome["competencia"]["depende_de_dados"] is True
    assert por_nome["competencia"]["documentos_com_dado"] == 4
    assert "Formação Geral" in por_nome["tipo_prova"]["valores"]
    assert por_nome["ano"]["valores"] == ["2021", "2022", "2023"]


def test_consulta_portugues():
    c = busca.montar_consulta("ética profissional", [])
    mm = c["bool"]["must"][0]["multi_match"]
    assert mm["minimum_should_match"] == "75%"
    assert c["bool"]["should"][0]["match_phrase"]["enunciado"]["query"] == "ética profissional"
    assert "texto_bruto" not in str(c)  # campo nao indexado (index: false) nao pode ser consultado


def test_adaptar_questao_documento_incompleto():
    q = busca.adaptar_questao("x-1", {"ano": 2020, "tipo_prova": "FG", "texto_completo": "texto"})
    Questao.model_validate(q)
    assert q["alternativas"] == [] and q["competencias"] == [] and q["gabarito"] is None
    assert q["enunciado"] == "texto" and q["tipo_prova"] == "Formação Geral"
