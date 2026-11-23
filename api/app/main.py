"""ENADE Search API.

Camada unica que o frontend consome: esconde Elasticsearch, Redis, LDAP e Kerberos.
Documentacao interativa: /docs (Swagger) e /redoc.
"""
import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from elasticsearch import AsyncElasticsearch
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config as configuracao
from .dependencias import Estado, obter_estado
from .erros import registrar_handlers
from .rotas import auth, cache, carrinho, questoes
from .seguranca.kerberos import ProvedorTokenKerberos
from .seguranca.ldap import AutenticadorLDAP
from .seguranca.sessoes import GerenciadorSessoes
from .servicos.cache import CacheConsultas
from .servicos.carrinho import Carrinho

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("enade.api")

VERSAO = "2.0.0"

DESCRICAO = """
API de pesquisa de questões do ENADE. O frontend consome **apenas** esta API
(nunca o Elasticsearch, o Redis, o Kafka ou o LDAP diretamente).

### Autenticação
1. `POST /api/auth/login` com `{"usuario": "...", "senha": "..."}` (validado no LDAP).
2. Envie o `access_token` recebido em `Authorization: Bearer <token>` (botão **Authorize**).
3. A sessão expira após `SESSAO_TTL` segundos sem uso.

| Perfil | Pode |
|---|---|
| anônimo | pesquisar, filtrar, ver estatísticas (sem gabarito) |
| `estudante` | o mesmo + carrinho e exportação **sem** gabarito |
| `professor` | tudo: gabaritos, painel analítico, exportação com gabarito, métricas/invalidação do cache |

Estudante acessando recurso de professor recebe **403** (`ACESSO_NEGADO`).

### Erros
Todos os erros seguem `{"erro": {"codigo": "...", "mensagem": "..."}}`
(400 parâmetros inválidos, 401 não autenticado, 403 sem permissão, 404 não encontrado,
409 conflito, 429 bloqueio de login, 500 erro interno, 503 serviço indisponível).
"""

TAGS = [
    {"name": "Status", "description": "Verificação de funcionamento."},
    {"name": "Autenticação", "description": "Login LDAP e sessão (Redis)."},
    {"name": "Questões e estatísticas", "description": "Pesquisa, filtros, detalhes, estatísticas e painel."},
    {"name": "Carrinho e exportação", "description": "Lista de questões da sessão e exportação de simulados."},
    {"name": "Cache", "description": "Métricas e invalidação do cache Redis (professor)."},
]


async def criar_estado(cfg: configuracao.Config) -> Estado:
    kerberos = None
    if cfg.es_auth == "kerberos":
        kerberos = ProvedorTokenKerberos(cfg.es_url, cfg.es_kerberos_servico,
                                         cfg.es_kerberos_principal, cfg.es_kerberos_keytab)
        token = await kerberos.obter_token()  # falha aqui = API nao sobe sem autenticacao mutua
        es = AsyncElasticsearch(cfg.es_url, api_key=token, request_timeout=cfg.es_timeout)
    else:
        es = AsyncElasticsearch(cfg.es_url, request_timeout=cfg.es_timeout)
    cliente_redis = redis.from_url(cfg.redis_url, password=cfg.redis_password, decode_responses=True)
    return Estado(
        cfg=cfg, es=es, redis=cliente_redis,
        cache=CacheConsultas(cliente_redis, cfg.cache_ttl),
        sessoes=GerenciadorSessoes(cliente_redis, cfg.sessao_ttl),
        carrinho=Carrinho(cliente_redis, cfg.sessao_ttl, cfg.carrinho_max),
        autenticador=AutenticadorLDAP(cfg),
        kerberos=kerberos,
    )


def criar_app(estado: Estado | None = None, cfg: configuracao.Config | None = None) -> FastAPI:
    """`estado` permite injetar dependencias falsas nos testes."""
    cfg = cfg or (estado.cfg if estado else configuracao.carregar())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.enade = estado or await criar_estado(cfg)
        yield
        if estado is None:
            await app.state.enade.es.close()
            await app.state.enade.redis.aclose()

    app = FastAPI(title="ENADE Search API", description=DESCRICAO, version=VERSAO,
                  openapi_tags=TAGS, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origens,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Cache", "Content-Disposition"],
    )
    registrar_handlers(app)

    @app.get("/", tags=["Status"], summary="API online")
    async def raiz():
        return {"projeto": "ENADE Search", "status": "online", "versao": VERSAO, "documentacao": "/docs"}

    @app.get("/api/health", tags=["Status"], summary="Saúde da API e dependências",
             description="Status de API, Elasticsearch e Redis (`online`/`offline`) e modo de autenticação "
                         "com o Elasticsearch. Sempre 200; consulte os campos.")
    async def health(est: Estado = Depends(obter_estado)):
        resultado = {"api": "online"}
        try:
            resultado["elasticsearch"] = "online" if await est.es.ping() else "offline"
        except Exception:
            resultado["elasticsearch"] = "offline"
        try:
            await est.redis.ping()
            resultado["redis"] = "online"
        except Exception:
            resultado["redis"] = "offline"
        resultado["autenticacao_elasticsearch"] = est.cfg.es_auth
        return resultado

    for r in (auth.router, questoes.router, carrinho.router, cache.router):
        app.include_router(r)
    return app


app = criar_app()
