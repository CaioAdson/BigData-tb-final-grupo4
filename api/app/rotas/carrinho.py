"""Carrinho de questoes (por sessao, no Redis) e exportacao do simulado."""
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from ..dependencias import Estado, UsuarioSessao, obter_es, obter_estado, usuario_obrigatorio
from ..erros import ErroAPI, sem_permissao, servico_indisponivel
from ..schemas import Carrinho, ItemCarrinhoEntrada, respostas_erro
from ..servicos import busca, exportacao
from ..servicos.carrinho import CarrinhoCheio
from .questoes import consultar

router = APIRouter(prefix="/api/carrinho", tags=["Carrinho e exportação"])


async def _redis(coro):
    try:
        return await coro
    except (ErroAPI, CarrinhoCheio):
        raise
    except Exception as e:
        raise servico_indisponivel("Redis (carrinho)") from e


async def _questoes(estado: Estado, es, ids: list[str]) -> list[dict]:
    """Busca as questoes no Elasticsearch preservando a ordem do carrinho."""
    if not ids:
        return []
    resposta = await consultar(es.mget(index=estado.cfg.es_index, ids=ids, source_includes=busca.CAMPOS_FONTE))
    return [busca.adaptar_questao(d["_id"], d.get("_source") or {})
            for d in resposta.get("docs", []) if d.get("found")]


async def _estado_carrinho(estado: Estado, es, usuario: UsuarioSessao) -> dict:
    ids = await _redis(estado.carrinho.ids(usuario.sid))
    pode_ver = usuario.pode("ver_gabarito")
    questoes = [busca.ocultar_gabarito(q, pode_ver) for q in await _questoes(estado, es, ids)]
    return {"total": len(questoes), "maximo": estado.carrinho.maximo,
            "expira_em": await _redis(estado.carrinho.expira_em(usuario.sid)), "questoes": questoes}


@router.get("", response_model=Carrinho, summary="Listar carrinho",
            description="Questões selecionadas nesta sessão, na ordem de inclusão. **Requer autenticação.**",
            responses=respostas_erro(401, 503))
async def listar(usuario: UsuarioSessao = Depends(usuario_obrigatorio),
                 estado: Estado = Depends(obter_estado), es=Depends(obter_es)):
    return await _estado_carrinho(estado, es, usuario)


@router.post("/questoes", response_model=Carrinho, status_code=201, summary="Adicionar questão",
             description="Adiciona uma questão existente ao carrinho (201). Se ela já estiver no carrinho, "
                         "nada muda e a resposta é 200. Limite: `CARRINHO_MAX`. **Requer autenticação.**",
             responses={200: {"model": Carrinho, "description": "Questão já estava no carrinho."},
                        **respostas_erro(400, 401, 404, 409, 503)})
async def adicionar(entrada: ItemCarrinhoEntrada, response: Response,
                    usuario: UsuarioSessao = Depends(usuario_obrigatorio),
                    estado: Estado = Depends(obter_estado), es=Depends(obter_es)):
    if not await _questoes(estado, es, [entrada.id]):
        raise ErroAPI(404, "QUESTAO_NAO_ENCONTRADA", f"Questao '{entrada.id}' nao encontrada.")
    try:
        adicionou = await _redis(estado.carrinho.adicionar(usuario.sid, entrada.id))
    except CarrinhoCheio:
        raise ErroAPI(409, "CARRINHO_CHEIO", f"O carrinho aceita no maximo {estado.carrinho.maximo} questoes.")
    if not adicionou:
        response.status_code = 200
    return await _estado_carrinho(estado, es, usuario)


@router.delete("/questoes/{questao_id}", response_model=Carrinho, summary="Remover questão",
               description="Remove uma questão do carrinho. **Requer autenticação.**",
               responses=respostas_erro(401, 404, 503))
async def remover(questao_id: str = Path(..., max_length=200),
                  usuario: UsuarioSessao = Depends(usuario_obrigatorio),
                  estado: Estado = Depends(obter_estado), es=Depends(obter_es)):
    if not await _redis(estado.carrinho.remover(usuario.sid, questao_id)):
        raise ErroAPI(404, "QUESTAO_NAO_ESTA_NO_CARRINHO", f"Questao '{questao_id}' nao esta no carrinho.")
    return await _estado_carrinho(estado, es, usuario)


@router.delete("", status_code=204, summary="Limpar carrinho",
               description="Remove todas as questões do carrinho. **Requer autenticação.**",
               responses=respostas_erro(401, 503))
async def limpar(usuario: UsuarioSessao = Depends(usuario_obrigatorio), estado: Estado = Depends(obter_estado)):
    await _redis(estado.carrinho.limpar(usuario.sid))
    return Response(status_code=204)


@router.get(
    "/exportar",
    summary="Exportar simulado (PDF ou JSON)",
    description=(
        "Gera o simulado com as questões do carrinho (enunciados, alternativas e metadados).\n\n"
        "- **professor**: exporta com gabarito (padrão) ou sem (`incluir_gabarito=false`).\n"
        "- **estudante**: exporta somente sem gabarito; pedir `incluir_gabarito=true` retorna **403**.\n\n"
        "**Requer autenticação.** Carrinho vazio retorna 400 (`CARRINHO_VAZIO`)."),
    responses={200: {"description": "Arquivo do simulado.",
                     "content": {"application/pdf": {}, "application/json": {}}},
               **respostas_erro(400, 401, 403, 503)},
)
async def exportar(
    formato: Literal["pdf", "json"] = Query("pdf", description="`pdf` ou `json`."),
    incluir_gabarito: bool | None = Query(None, description="Padrão: true para professor, false para estudante."),
    usuario: UsuarioSessao = Depends(usuario_obrigatorio),
    estado: Estado = Depends(obter_estado), es=Depends(obter_es),
):
    pode_ver = usuario.pode("ver_gabarito")
    if incluir_gabarito and not pode_ver:
        raise sem_permissao("Somente professores podem exportar simulados com gabarito.")
    com_gabarito = pode_ver if incluir_gabarito is None else incluir_gabarito

    ids = await _redis(estado.carrinho.ids(usuario.sid))
    questoes = await _questoes(estado, es, ids)
    if not questoes:
        raise ErroAPI(400, "CARRINHO_VAZIO", "Adicione questoes ao carrinho antes de exportar.")

    simulado = exportacao.montar_simulado(questoes, usuario.como_dict(), com_gabarito)
    nome = f"simulado-enade-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if formato == "json":
        conteudo = json.dumps(simulado, ensure_ascii=False, indent=2).encode("utf-8")
        tipo = "application/json"
    else:
        conteudo = exportacao.gerar_pdf(simulado)
        tipo = "application/pdf"
    return Response(content=conteudo, media_type=tipo,
                    headers={"Content-Disposition": f'attachment; filename="{nome}.{formato}"'})
