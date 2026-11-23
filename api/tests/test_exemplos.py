"""Os exemplos JSON entregues ao frontend (api/exemplos) seguem o contrato da API."""
import json
from pathlib import Path

import pytest

from app import schemas

EXEMPLOS = Path(__file__).resolve().parents[1] / "exemplos"
MODELOS = {
    "auth_login_professor": schemas.Token, "auth_login_estudante": schemas.Token, "auth_me": schemas.Usuario,
    "questoes_pesquisa": schemas.RespostaQuestoes, "questoes_pesquisa_professor": schemas.RespostaQuestoes,
    "questoes_vazia": schemas.RespostaQuestoes, "questoes_filtros": schemas.RespostaFiltros,
    "questao_detalhe": schemas.Questao, "estatisticas": schemas.Estatisticas, "carrinho": schemas.Carrinho,
    "painel_professor": schemas.PainelProfessor, "cache_metricas": schemas.MetricasCache,
}


@pytest.mark.parametrize("nome,modelo", MODELOS.items())
def test_exemplo_valida_contrato(nome, modelo):
    dados = json.loads((EXEMPLOS / f"{nome}.json").read_text(encoding="utf-8"))
    modelo.model_validate(dados)


def test_exemplos_de_erro():
    erros = json.loads((EXEMPLOS / "erros.json").read_text(encoding="utf-8"))
    for corpo in erros.values():
        schemas.Erro.model_validate(corpo)


def test_exemplos_atualizados():
    """Falha se o contrato mudou e os exemplos nao foram regenerados (python gerar_exemplos.py)."""
    import gerar_exemplos
    for nome, dados in gerar_exemplos.gerar().items():
        if nome == "cache_metricas":
            continue
        salvo = json.loads((EXEMPLOS / f"{nome}.json").read_text(encoding="utf-8"))
        assert salvo == json.loads(json.dumps(dados, ensure_ascii=False)), f"regenere api/exemplos/{nome}.json"
