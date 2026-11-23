"""Montagem de consultas ao Elasticsearch e adaptacao dos documentos ao contrato da API.

Campos de texto do indice usam o analisador `pt_indexacao`/`pt_busca` (stemming brazilian,
stopwords, asciifolding e sinonimos), definido em ingestao/enade/indice.py.
"""
import unicodedata

TIPOS_PROVA = {"FG": "Formação Geral", "CE": "Componente Específico"}
TIPOS_QUESTAO = {"objetiva", "discursiva"}

# Pesos: enunciado e o mais informativo; alternativas e texto-base ajudam, mas pesam menos.
CAMPOS_BUSCA = ["enunciado^3", "texto_base^1.5", "alternativas.texto", "texto_completo", "curso.texto^0.5"]
CAMPOS_DESTAQUE = ["enunciado", "texto_base", "alternativas.texto"]
JANELA_MAXIMA = 10_000  # index.max_result_window padrao do Elasticsearch


def _sem_acento(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def normalizar_tipo_prova(valor: str | None) -> str | None:
    """Aceita 'FG', 'CE', 'Formação Geral', 'formacao geral', 'Componente Específico'...
    e devolve o codigo armazenado no indice ('FG'/'CE'). Retorna None se invalido."""
    if valor is None:
        return None
    v = _sem_acento(valor)
    if v in {"fg", "formacao geral"}:
        return "FG"
    if v in {"ce", "componente especifico"}:
        return "CE"
    return None


def normalizar_tipo_questao(valor: str | None) -> str | None:
    if valor is None:
        return None
    v = _sem_acento(valor)
    return v if v in TIPOS_QUESTAO else None


def montar_filtros(*, area=None, curso=None, ano=None, tipo_prova=None, tipo_questao=None,
                   competencia=None) -> list[dict]:
    """Filtros combinaveis (AND). Todos sao `term` em campos keyword: nao afetam o score
    e sao cacheados pelo proprio Elasticsearch."""
    filtros = []
    if area:
        filtros.append({"term": {"area": area}})
    if curso:
        filtros.append({"term": {"curso": curso}})
    if ano is not None:
        filtros.append({"term": {"ano": ano}})
    if tipo_prova:
        filtros.append({"term": {"tipo_prova": tipo_prova}})
    if tipo_questao:
        filtros.append({"term": {"tipo_questao": tipo_questao}})
    if competencia:
        filtros.append({"term": {"competencias": competencia}})
    return filtros


def montar_consulta(q: str | None, filtros: list[dict]) -> dict:
    """Consulta textual em portugues.

    - multi_match `best_fields` nos campos analisados com stemming PT-BR (ex.: 'algoritmo'
      encontra 'algoritmos'; sinonimos de mapping/sinonimos.txt sao aplicados na busca);
    - `minimum_should_match` 75% evita que um unico termo comum traga resultados irrelevantes
      em consultas longas;
    - frase exata (match_phrase com slop 2) recebe bonus para subir resultados mais precisos.
    """
    consulta: dict = {"bool": {"filter": filtros}}
    if q:
        consulta["bool"]["must"] = [{
            "multi_match": {
                "query": q,
                "fields": CAMPOS_BUSCA,
                "type": "best_fields",
                "operator": "or",
                "minimum_should_match": "75%",
                "tie_breaker": 0.3,
            }
        }]
        consulta["bool"]["should"] = [
            {"match_phrase": {"enunciado": {"query": q, "slop": 2, "boost": 2}}},
            {"match_phrase": {"texto_completo": {"query": q, "slop": 2}}},
        ]
    else:
        consulta["bool"]["must"] = [{"match_all": {}}]
    return consulta


def montar_destaque() -> dict:
    return {
        "pre_tags": ["<mark>"],
        "post_tags": ["</mark>"],
        "encoder": "html",  # escapa HTML do texto original; so <mark> fica como tag
        "fields": {
            "enunciado": {"fragment_size": 200, "number_of_fragments": 3},
            "texto_base": {"fragment_size": 200, "number_of_fragments": 2},
            "alternativas.texto": {"fragment_size": 150, "number_of_fragments": 5},
        },
    }


def ordenacao(q: str | None) -> list:
    # Sem texto, a relevancia e indiferente: ordem estavel e previsivel para paginar.
    if q:
        return ["_score", {"ano": "desc"}, {"numero": "asc"}]
    return [{"ano": "desc"}, {"tipo_prova": "desc"}, {"numero": "asc"}]


def adaptar_questao(doc_id: str, fonte: dict) -> dict:
    """Converte o documento interno do indice para o contrato publico `Questao`."""
    alternativas = [
        {"letra": str(a.get("letra", "")), "texto": str(a.get("texto", ""))}
        for a in (fonte.get("alternativas") or []) if isinstance(a, dict)
    ]
    tipo = fonte.get("tipo_prova")
    return {
        "id": fonte.get("id") or doc_id,
        "ano": int(fonte.get("ano") or 0),
        "area": fonte.get("area") or "",
        "curso": fonte.get("curso") or "",
        "tipo_prova": TIPOS_PROVA.get(tipo, "Componente Específico"),
        "tipo_questao": fonte.get("tipo_questao") if fonte.get("tipo_questao") in TIPOS_QUESTAO else "objetiva",
        "numero": int(fonte.get("numero") or 0),
        "texto_base": fonte.get("texto_base") or None,
        "enunciado": fonte.get("enunciado") or fonte.get("texto_completo") or "",
        "alternativas": alternativas,
        "gabarito": fonte.get("gabarito") or None,
        "anulada": bool(fonte.get("anulada", False)),
        "competencias": list(fonte.get("competencias") or []),
        "objetos_conhecimento": list(fonte.get("objetos_conhecimento") or []),
    }


def adaptar_destaques(highlight: dict | None) -> dict[str, list[str]]:
    if not highlight:
        return {}
    nomes = {"alternativas.texto": "alternativas"}
    return {nomes.get(campo, campo): trechos for campo, trechos in highlight.items()}


def ocultar_gabarito(questao: dict, pode_ver: bool) -> dict:
    if not pode_ver:
        questao = {**questao, "gabarito": None}
    return questao


CAMPOS_FONTE = ["id", "ano", "area", "curso", "tipo_prova", "tipo_questao", "numero", "texto_base",
                "enunciado", "alternativas", "gabarito", "anulada", "competencias", "objetos_conhecimento",
                "texto_completo"]
