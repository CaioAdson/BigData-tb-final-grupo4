import hashlib
import json
import os
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

import redis.asyncio as redis
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, HTTPException, Query

ES_URL = os.getenv("ES_URL", "http://localhost:9200")
ES_INDEX = os.getenv("ES_INDEX", "enade-questoes")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))

es = None
cache = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global es, cache
    es = AsyncElasticsearch(ES_URL)
    cache = redis.from_url(REDIS_URL, password=os.getenv("REDIS_PASSWORD"), decode_responses=True)
    yield
    await es.close()
    await cache.aclose()


app = FastAPI(
    title="ENADE Search API",
    description="API de busca de questões do ENADE",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def consultar_cache(chave: str):
    try:
        valor = await cache.get(chave)
        return json.loads(valor) if valor else None
    except Exception:
        return None


async def salvar_cache(chave: str, dados: dict):
    try:
        await cache.setex(chave, CACHE_TTL, json.dumps(dados, ensure_ascii=False))
    except Exception:
        pass


def gerar_chave_cache(parametros: dict) -> str:
    conteudo = json.dumps(parametros, sort_keys=True, ensure_ascii=False)
    return "enade:api:" + hashlib.sha256(conteudo.encode()).hexdigest()


@app.get("/")
async def raiz():
    return {"projeto": "ENADE Search", "status": "online"}


@app.get("/api/health")
async def health():
    resultado = {"api": "online"}
    try:
        await es.ping()
        resultado["elasticsearch"] = "online"
    except Exception:
        resultado["elasticsearch"] = "offline"

    try:
        await cache.ping()
        resultado["redis"] = "online"
    except Exception:
        resultado["redis"] = "offline"

    return resultado


@app.get("/api/questoes")
async def buscar_questoes(
    q: str | None = Query(default=None, description="Texto para pesquisa"),
    area: str | None = None,
    ano: int | None = None,
    tipo_prova: str | None = None,
    tipo_questao: str | None = None,
    pagina: int = Query(default=1, ge=1),
    tamanho: int = Query(default=10, ge=1, le=100),
):
    parametros = {
        "q": q, "area": area, "ano": ano,
        "tipo_prova": tipo_prova, "tipo_questao": tipo_questao,
        "pagina": pagina, "tamanho": tamanho,
    }
    chave = gerar_chave_cache(parametros)
    armazenado = await consultar_cache(chave)
    if armazenado is not None:
        armazenado["cache"] = "hit"
        return armazenado

    filtros = []
    if area:
        filtros.append({"term": {"area": area}})
    if ano is not None:
        filtros.append({"term": {"ano": ano}})
    if tipo_prova:
        filtros.append({"term": {"tipo_prova": tipo_prova}})
    if tipo_questao:
        filtros.append({"term": {"tipo_questao": tipo_questao}})

    consulta = {"bool": {"filter": filtros}}
    if q:
        consulta["bool"]["must"] = [
            {
                "multi_match": {
                    "query": q,
                    "fields": ["texto_bruto", "enunciado", "alternativas.texto"],
                    "type": "best_fields",
                }
            }
        ]
    else:
        consulta["bool"]["must"] = [{"match_all": {}}]

    try:
        resposta = await es.search(
            index=ES_INDEX,
            query=consulta,
            from_=(pagina - 1) * tamanho,
            size=tamanho,
        )
    except Exception as erro:
        raise HTTPException(status_code=503, detail="Falha ao consultar Elasticsearch") from erro

    resultado = {
        "total": resposta["hits"]["total"]["value"],
        "pagina": pagina,
        "tamanho": tamanho,
        "questoes": [
            {"id": item["_id"], **item["_source"]}
            for item in resposta["hits"]["hits"]
        ],
        "cache": "miss",
    }
    await salvar_cache(chave, resultado)
    return resultado


@app.get("/api/estatisticas")
async def estatisticas():
    parametros = {"endpoint": "estatisticas"}
    chave = gerar_chave_cache(parametros)
    armazenado = await consultar_cache(chave)
    if armazenado is not None:
        armazenado["cache"] = "hit"
        return armazenado

    agregacoes = {
        "por_area": {"terms": {"field": "area", "size": 50}},
        "por_ano": {"terms": {"field": "ano", "size": 20}},
        "por_tipo_questao": {"terms": {"field": "tipo_questao", "size": 10}},
        "por_tipo_prova": {"terms": {"field": "tipo_prova", "size": 10}},
    }

    try:
        resposta = await es.search(
            index=ES_INDEX,
            size=0,
            aggs=agregacoes,
        )
    except Exception as erro:
        raise HTTPException(status_code=503, detail="Falha ao consultar Elasticsearch") from erro

    resultado = {
        "total_questoes": resposta["hits"]["total"]["value"],
        "agregacoes": {
            nome: [
                {"valor": item["key"], "quantidade": item["doc_count"]}
                for item in resposta["aggregations"][nome]["buckets"]
            ]
            for nome in agregacoes
        },
        "cache": "miss",
    }
    await salvar_cache(chave, resultado)
    return resultado

