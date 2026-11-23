"""Metricas e invalidacao do cache de consultas (somente professor)."""
from fastapi import APIRouter, Depends

from ..dependencias import Estado, UsuarioSessao, exigir_permissao, obter_estado
from ..erros import servico_indisponivel
from ..schemas import InvalidacaoCache, MetricasCache, respostas_erro

router = APIRouter(prefix="/api/cache", tags=["Cache"])
professor = exigir_permissao("gerenciar_cache", "Gerenciamento do cache exclusivo para professores.")


@router.get("/metricas", response_model=MetricasCache, summary="Métricas do cache",
            description="Hits, misses, erros, hit rate (total e por endpoint), chaves ativas, TTL e versão. "
                        "**Requer perfil professor.**",
            responses=respostas_erro(401, 403, 503))
async def metricas(_: UsuarioSessao = Depends(professor), estado: Estado = Depends(obter_estado)):
    try:
        return await estado.cache.metricas()
    except Exception as e:
        raise servico_indisponivel("Redis") from e


@router.post("/invalidar", response_model=InvalidacaoCache, summary="Invalidar cache",
             description="Invalida todas as consultas em cache (incrementa a versão; entradas antigas deixam de "
                         "ser lidas e expiram pelo TTL). Use após reindexar o acervo. **Requer perfil professor.**",
             responses=respostas_erro(401, 403, 503))
async def invalidar(_: UsuarioSessao = Depends(professor), estado: Estado = Depends(obter_estado)):
    try:
        versao = await estado.cache.invalidar()
    except Exception as e:
        raise servico_indisponivel("Redis") from e
    return {"versao": versao, "mensagem": "Cache de consultas invalidado."}
