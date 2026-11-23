"""Pesquisa de questoes, detalhes, filtros disponiveis, estatisticas e painel do professor."""
import logging
import math

from elasticsearch import ApiError, NotFoundError
from elasticsearch import ConnectionError as ESConnectionError
from elasticsearch import TransportError
from fastapi import APIRouter, Depends, Path, Query, Response

from ..dependencias import (Estado, UsuarioSessao, exigir_permissao, obter_es, obter_estado,
                            usuario_opcional)
from ..erros import ErroAPI, servico_indisponivel
from ..schemas import (Estatisticas, PainelProfessor, Questao, RespostaFiltros, RespostaQuestoes,
                       respostas_erro)
from ..servicos import busca, estatisticas as est

log = logging.getLogger("enade.api")
router = APIRouter(prefix="/api", tags=["Questões e estatísticas"])

RESULTADO_VAZIO_ES = {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}


def _indice_inexistente(e: Exception) -> bool:
    return isinstance(e, NotFoundError) and "index_not_found" in str(e)


async def consultar(chamada):
    """Executa a chamada ao Elasticsearch traduzindo falhas para o padrao de erro da API.
    Indice ainda nao criado = acervo vazio (estrutura de resposta mantida)."""
    try:
        return await chamada
    except NotFoundError as e:
        if _indice_inexistente(e):
            return RESULTADO_VAZIO_ES
        raise
    except (ESConnectionError, TransportError) as e:
        log.warning("Elasticsearch indisponivel: %s", type(e).__name__)
        raise servico_indisponivel("Elasticsearch") from e
    except ApiError as e:
        if getattr(e, "status_code", 500) in (401, 403):
            log.error("Elasticsearch recusou as credenciais da API: %s", e)
            raise servico_indisponivel("Elasticsearch (autenticacao)") from e
        if getattr(e, "status_code", 500) == 400:
            raise ErroAPI(400, "CONSULTA_INVALIDA", "Consulta de pesquisa invalida.") from e
        raise servico_indisponivel("Elasticsearch") from e


@router.get(
    "/questoes",
    response_model=RespostaQuestoes,
    summary="Pesquisar questões",
    description=(
        "Pesquisa textual em português (stemming, sinônimos, sem acentos) com filtros combináveis (AND) e "
        "paginação. Os termos encontrados voltam em `destaques` envoltos em `<mark>`.\n\n"
        "**Autenticação:** opcional. O `gabarito` só é preenchido para o perfil **professor**; "
        "anônimos e estudantes recebem `null`.\n\n"
        "O header `X-Cache: HIT|MISS` indica se a resposta veio do cache Redis (TTL `CACHE_TTL`).\n\n"
        "Exemplo: `GET /api/questoes?q=algoritmos&area=Computação&ano=2023&pagina=1&tamanho=10`"),
    responses=respostas_erro(400, 401, 503),
)
async def pesquisar_questoes(
    response: Response,
    q: str | None = Query(None, max_length=300, description="Texto para pesquisa.", examples=["algoritmos"]),
    area: str | None = Query(None, max_length=120, description="Área exata.", examples=["Computação"]),
    curso: str | None = Query(None, max_length=200, description="Curso exato.", examples=["Sistemas de Informação"]),
    ano: int | None = Query(None, ge=2004, le=2100, description="Ano da prova.", examples=[2023]),
    tipo_prova: str | None = Query(None, description="`Formação Geral` ou `Componente Específico` (aceita `FG`/`CE`)."),
    tipo_questao: str | None = Query(None, description="`objetiva` ou `discursiva`."),
    competencia: str | None = Query(None, max_length=200, description="Competência exata."),
    pagina: int = Query(1, ge=1, description="Página solicitada."),
    tamanho: int = Query(10, ge=1, le=100, description="Questões por página."),
    usuario: UsuarioSessao | None = Depends(usuario_opcional),
    estado: Estado = Depends(obter_estado),
    es=Depends(obter_es),
):
    detalhes = []
    tp = busca.normalizar_tipo_prova(tipo_prova)
    if tipo_prova is not None and tp is None:
        detalhes.append({"campo": "tipo_prova", "mensagem": "Use 'Formação Geral' ou 'Componente Específico' (ou FG/CE)."})
    tq = busca.normalizar_tipo_questao(tipo_questao)
    if tipo_questao is not None and tq is None:
        detalhes.append({"campo": "tipo_questao", "mensagem": "Use 'objetiva' ou 'discursiva'."})
    if pagina * tamanho > busca.JANELA_MAXIMA:
        detalhes.append({"campo": "pagina", "mensagem": f"pagina x tamanho nao pode passar de {busca.JANELA_MAXIMA}."})
    if detalhes:
        raise ErroAPI(400, "PARAMETROS_INVALIDOS", "Um ou mais parametros sao invalidos.", detalhes)

    def limpo(v):
        return v.strip() or None if isinstance(v, str) else v

    q, area, curso, competencia = limpo(q), limpo(area), limpo(curso), limpo(competencia)
    parametros = {"q": q, "area": area, "curso": curso, "ano": ano, "tipo_prova": tp, "tipo_questao": tq,
                  "competencia": competencia, "pagina": pagina, "tamanho": tamanho}

    resultado = await estado.cache.obter("questoes", parametros)
    response.headers["X-Cache"] = "HIT" if resultado is not None else "MISS"
    if resultado is None:
        filtros = busca.montar_filtros(area=area, curso=curso, ano=ano, tipo_prova=tp,
                                       tipo_questao=tq, competencia=competencia)
        corpo = dict(
            index=estado.cfg.es_index,
            query=busca.montar_consulta(q, filtros),
            sort=busca.ordenacao(q),
            from_=(pagina - 1) * tamanho,
            size=tamanho,
            source=busca.CAMPOS_FONTE,
            track_total_hits=True,
        )
        if q:
            corpo["highlight"] = busca.montar_destaque()
        resposta = await consultar(es.search(**corpo))
        total = resposta["hits"]["total"]["value"]
        resultado = {
            "total": total,
            "pagina": pagina,
            "tamanho": tamanho,
            "total_paginas": math.ceil(total / tamanho) if total else 0,
            "questoes": [
                {**busca.adaptar_questao(h["_id"], h.get("_source") or {}),
                 "destaques": busca.adaptar_destaques(h.get("highlight"))}
                for h in resposta["hits"]["hits"]
            ],
        }
        await estado.cache.salvar("questoes", parametros, resultado)

    # O cache guarda a versao completa; o gabarito e removido conforme o perfil de quem pede.
    pode_ver = bool(usuario and usuario.pode("ver_gabarito"))
    resultado["questoes"] = [busca.ocultar_gabarito(x, pode_ver) for x in resultado["questoes"]]
    return resultado


@router.get(
    "/questoes/filtros",
    response_model=RespostaFiltros,
    summary="Filtros disponíveis",
    description="Lista os parâmetros de `/api/questoes`, se cada filtro está implementado, se depende de "
                "metadados que podem faltar no índice (ex.: `competencia`), quantas questões têm o dado "
                "e os valores existentes (para montar selects no frontend). Público.",
    responses=respostas_erro(503),
)
async def filtros_disponiveis(response: Response, estado: Estado = Depends(obter_estado), es=Depends(obter_es)):
    dados = await estado.cache.obter("filtros", {})
    response.headers["X-Cache"] = "HIT" if dados is not None else "MISS"
    if dados is None:
        resposta = await consultar(es.search(index=estado.cfg.es_index, size=0, track_total_hits=True,
                                             aggs=est.agregacoes_filtros()))
        dados = est.adaptar_filtros(resposta)
        await estado.cache.salvar("filtros", {}, dados)
    return dados


@router.get(
    "/questoes/{questao_id}",
    response_model=Questao,
    summary="Detalhes de uma questão",
    description="Retorna uma questão pelo `id`. Autenticação opcional; `gabarito` só para professor.",
    responses=respostas_erro(401, 404, 503),
)
async def obter_questao(
    questao_id: str = Path(..., max_length=200, examples=["sistemas-de-informacao-2023-fg-001"]),
    usuario: UsuarioSessao | None = Depends(usuario_opcional),
    estado: Estado = Depends(obter_estado),
    es=Depends(obter_es),
):
    try:
        doc = await consultar(es.get(index=estado.cfg.es_index, id=questao_id, source_includes=busca.CAMPOS_FONTE))
    except NotFoundError:
        doc = {"found": False}
    if not doc.get("found"):
        raise ErroAPI(404, "QUESTAO_NAO_ENCONTRADA", f"Questao '{questao_id}' nao encontrada.")
    questao = busca.adaptar_questao(doc["_id"], doc.get("_source") or {})
    return busca.ocultar_gabarito(questao, bool(usuario and usuario.pode("ver_gabarito")))


async def _estatisticas(estado: Estado, es) -> tuple[dict, bool]:
    dados = await estado.cache.obter("estatisticas", {})
    if dados is not None:
        return dados, True
    resposta = await consultar(es.search(index=estado.cfg.es_index, size=0, track_total_hits=True,
                                         aggs=est.agregacoes_estatisticas()))
    dados = est.adaptar_estatisticas(resposta)
    await estado.cache.salvar("estatisticas", {}, dados)
    return dados, False


@router.get(
    "/estatisticas",
    response_model=Estatisticas,
    summary="Estatísticas do acervo",
    description="Totais por área, ano, tipo de questão, tipo de prova e curso, e histograma de questões por "
                "competência ao longo dos anos. Informação indisponível vem como lista vazia/zero, mantendo a "
                "estrutura. Público. Cacheado no Redis (`X-Cache`).",
    responses=respostas_erro(503),
)
async def estatisticas(response: Response, estado: Estado = Depends(obter_estado), es=Depends(obter_es)):
    dados, hit = await _estatisticas(estado, es)
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
    return dados


@router.get(
    "/painel/professor",
    response_model=PainelProfessor,
    summary="Painel analítico (somente professor)",
    description="Estatísticas completas + cobertura de gabaritos e anulações por ano, indicadores de "
                "qualidade da extração e métricas do cache. **Requer perfil professor** (estudante recebe 403).",
    responses=respostas_erro(401, 403, 503),
)
async def painel_professor(
    _: UsuarioSessao = Depends(exigir_permissao("painel_analitico", "Painel analitico exclusivo para professores.")),
    estado: Estado = Depends(obter_estado),
    es=Depends(obter_es),
):
    dados_est, _hit = await _estatisticas(estado, es)
    resposta = await consultar(es.search(index=estado.cfg.es_index, size=0, track_total_hits=True,
                                         aggs=est.agregacoes_painel()))
    try:
        metricas = await estado.cache.metricas()
    except Exception as e:
        raise servico_indisponivel("Redis") from e
    return {"estatisticas": dados_est, **est.adaptar_painel(resposta), "cache": metricas}
