"""Agregacoes do Elasticsearch adaptadas ao contrato de estatisticas.

Todos os campos agregados sao `keyword`/`short` no mapping (ingestao/enade/indice.py),
entao `terms` funciona sem fielddata.
"""
from .busca import TIPOS_PROVA


def agregacoes_estatisticas() -> dict:
    return {
        "por_area": {"terms": {"field": "area", "size": 100}},
        "por_ano": {"terms": {"field": "ano", "size": 100, "order": {"_key": "asc"}}},
        "por_tipo_questao": {"terms": {"field": "tipo_questao", "size": 10}},
        "por_tipo_prova": {"terms": {"field": "tipo_prova", "size": 10}},
        "por_curso": {"terms": {"field": "curso", "size": 500}},
        "competencias_por_ano": {
            "terms": {"field": "competencias", "size": 200},
            "aggs": {"por_ano": {"terms": {"field": "ano", "size": 100, "order": {"_key": "asc"}}}},
        },
    }


def _buckets(resposta: dict, nome: str) -> list[dict]:
    return ((resposta.get("aggregations") or {}).get(nome) or {}).get("buckets") or []


def _contagem(resposta: dict, nome: str, rotulo=lambda k: str(k)) -> list[dict]:
    return [{"nome": rotulo(b["key"]), "quantidade": b["doc_count"]} for b in _buckets(resposta, nome)]


def total_hits(resposta: dict) -> int:
    total = (resposta.get("hits") or {}).get("total") or 0
    return total.get("value", 0) if isinstance(total, dict) else int(total)


def adaptar_estatisticas(resposta: dict) -> dict:
    return {
        "total_questoes": total_hits(resposta),
        "por_area": _contagem(resposta, "por_area"),
        "por_ano": _contagem(resposta, "por_ano", lambda k: str(int(k))),
        "por_tipo_questao": _contagem(resposta, "por_tipo_questao"),
        "por_tipo_prova": _contagem(resposta, "por_tipo_prova", lambda k: TIPOS_PROVA.get(k, str(k))),
        "por_curso": _contagem(resposta, "por_curso"),
        "competencias_por_ano": [
            {
                "competencia": b["key"],
                "total": b["doc_count"],
                "por_ano": [{"ano": int(a["key"]), "quantidade": a["doc_count"]}
                            for a in (b.get("por_ano") or {}).get("buckets", [])],
            }
            for b in _buckets(resposta, "competencias_por_ano")
        ],
    }


def agregacoes_painel() -> dict:
    por_ano = {"terms": {"field": "ano", "size": 100, "order": {"_key": "asc"}}}
    return {
        "gabaritos": {"filter": {"bool": {"filter": [{"term": {"tipo_questao": "objetiva"}},
                                                      {"exists": {"field": "gabarito"}}]}},
                      "aggs": {"por_ano": por_ano}},
        "anuladas": {"filter": {"term": {"anulada": True}}, "aggs": {"por_ano": por_ano}},
        "sem_gabarito": {"filter": {"term": {"qualidade.sem_gabarito": True}}},
        "segmentacao_incerta": {"filter": {"term": {"qualidade.segmentacao_incerta": True}}},
        "alternativas_incompletas": {"filter": {"term": {"qualidade.alternativas_incompletas": True}}},
        "midia_pendente": {"filter": {"term": {"midia_pendente": True}}},
        "com_competencias": {"filter": {"exists": {"field": "competencias"}}},
    }


def adaptar_painel(resposta: dict) -> dict:
    ag = resposta.get("aggregations") or {}

    def qtd(nome):
        return (ag.get(nome) or {}).get("doc_count", 0)

    def por_ano(nome):
        return [{"ano": int(b["key"]), "quantidade": b["doc_count"]}
                for b in ((ag.get(nome) or {}).get("por_ano") or {}).get("buckets", [])]

    total = total_hits(resposta)
    return {
        "gabaritos_por_ano": por_ano("gabaritos"),
        "anuladas_por_ano": por_ano("anuladas"),
        "qualidade": {
            "anuladas": qtd("anuladas"),
            "sem_gabarito": qtd("sem_gabarito"),
            "segmentacao_incerta": qtd("segmentacao_incerta"),
            "alternativas_incompletas": qtd("alternativas_incompletas"),
            "midia_pendente": qtd("midia_pendente"),
            "sem_competencias": max(total - qtd("com_competencias"), 0),
        },
    }


# Filtros de /api/questoes e o metadado de que cada um depende
FILTROS = [
    ("q", "string", "Pesquisa textual (enunciado, texto-base, alternativas) com stemming PT-BR.", "texto_completo", False),
    ("area", "string", "Filtra pela área exata (ex.: Computação).", "area", True),
    ("curso", "string", "Filtra pelo curso exato (ex.: Sistemas de Informação).", "curso", True),
    ("ano", "integer", "Filtra pelo ano da prova (2004-2100).", "ano", True),
    ("tipo_prova", "string", "'Formação Geral' ou 'Componente Específico' (aceita FG/CE).", "tipo_prova", True),
    ("tipo_questao", "string", "'objetiva' ou 'discursiva'.", "tipo_questao", True),
    ("competencia", "string", "Filtra por competência. Depende do enriquecimento do índice.", "competencias", True),
    ("pagina", "integer", "Página solicitada (>= 1).", None, False),
    ("tamanho", "integer", "Questões por página (1-100).", None, False),
]


def agregacoes_filtros() -> dict:
    ag = {}
    for parametro, _, _, campo, facetavel in FILTROS:
        if campo:
            ag[f"existe_{parametro}"] = {"filter": {"exists": {"field": campo}}}
        if facetavel:
            ag[f"valores_{parametro}"] = {"terms": {"field": campo, "size": 200, "order": {"_key": "asc"}}}
    return ag


def adaptar_filtros(resposta: dict) -> dict:
    ag = resposta.get("aggregations") or {}
    total = total_hits(resposta)
    filtros = []
    for parametro, tipo, descricao, campo, facetavel in FILTROS:
        if campo:
            com_dado = (ag.get(f"existe_{parametro}") or {}).get("doc_count", 0)
        else:
            com_dado = total
        valores = []
        if facetavel:
            for b in (ag.get(f"valores_{parametro}") or {}).get("buckets", []):
                k = b["key"]
                if parametro == "tipo_prova":
                    k = TIPOS_PROVA.get(k, k)
                valores.append(str(int(k)) if parametro == "ano" else str(k))
        filtros.append({
            "parametro": parametro, "tipo": tipo, "descricao": descricao, "implementado": True,
            "depende_de_dados": parametro == "competencia",
            "documentos_com_dado": com_dado, "disponivel": com_dado > 0, "valores": valores,
        })
    return {"total_questoes": total, "filtros": filtros}
