"""Definicao do indice Elasticsearch (RF13): analisador PT-BR com stemming e sinonimos.

- Indexacao: lowercase -> stop (_brazilian_) -> asciifolding -> stemmer brazilian
- Busca:     lowercase -> stop -> asciifolding -> sinonimos -> stemmer
  Sinonimos so na busca (synonym_graph updateable): editar mapping/sinonimos.txt
  nao exige reindexar o acervo (basta recarregar o analisador).
Uso: python -m enade.indice --mostrar | --criar | --recriar
"""
import argparse
import json
import sys

from . import config


STOPWORDS_PROIBIDAS = {
    "a", "o", "as", "os", "um", "uma", "e", "ou", "de", "da", "do", "das", "dos", "em", "no", "na",
    "nos", "nas", "por", "para", "com", "sem", "que", "se", "ao", "aos", "sobre", "entre", "mais", "como",
}


def validar_regras(regras: list[str]) -> None:
    for r in regras:
        for termo in r.replace(",", " ").lower().split():
            if termo in STOPWORDS_PROIBIDAS:
                raise ValueError(f"regra de sinonimo '{r}' contem a stopword '{termo}'; remova-a em mapping/sinonimos.txt")


def carregar_sinonimos() -> list[str]:
    arq = config.DIR_MAPPING / "sinonimos.txt"
    if not arq.exists():
        return []
    regras = [l.strip() for l in arq.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    validar_regras(regras)
    return regras


def definicao() -> dict:
    texto_pt = {"type": "text", "analyzer": "pt_indexacao", "search_analyzer": "pt_busca"}
    sinonimos = carregar_sinonimos() or ["etica, moral"]
    return {
        "settings": {
            "number_of_shards": config.ES_SHARDS,
            "number_of_replicas": config.ES_REPLICAS,
            "analysis": {
                "filter": {
                    "pt_stop": {"type": "stop", "stopwords": "_brazilian_"},
                    "pt_stemmer": {"type": "stemmer", "language": "brazilian"},
                    "pt_sinonimos": {"type": "synonym_graph", "synonyms": sinonimos, "updateable": True},
                },
                "analyzer": {
                    "pt_indexacao": {"tokenizer": "standard",
                                     "filter": ["lowercase", "pt_stop", "asciifolding", "pt_stemmer"]},
                    "pt_busca": {"tokenizer": "standard",
                                 "filter": ["lowercase", "pt_stop", "asciifolding", "pt_sinonimos", "pt_stemmer"]},
                },
            },
        },
        "mappings": {
            "dynamic": "strict",  # campo inesperado -> 400 -> DLQ (RF11)
            "properties": {
                "id": {"type": "keyword"},
                "area": {"type": "keyword"},
                "curso": {"type": "keyword", "fields": {"texto": texto_pt}},
                "ano": {"type": "short"},
                "tipo_prova": {"type": "keyword"},
                "tipo_questao": {"type": "keyword"},
                "numero": {"type": "short"},
                "anulada": {"type": "boolean"},
                "texto_base": texto_pt,
                "enunciado": texto_pt,
                "alternativas": {"properties": {"letra": {"type": "keyword"}, "texto": texto_pt}},
                "gabarito": {"type": "keyword"},
                "competencias": {"type": "keyword"},
                "objetos_conhecimento": {"type": "keyword"},
                "texto_completo": texto_pt,
                "texto_bruto": {"type": "text", "index": False},
                "midia_pendente": {"type": "boolean"},
                "midia": {"properties": {
                    "tipo": {"type": "keyword"}, "pagina": {"type": "short"},
                    "bbox": {"type": "float", "index": False},
                    "formato": {"type": "keyword"}, "status": {"type": "keyword"},
                    "conteudo": {"type": "text", "index": False},
                    "arquivo": {"type": "keyword", "index": False},
                }},
                "origem": {"properties": {
                    "pdf": {"type": "keyword"},
                    "pagina_inicio": {"type": "short"}, "pagina_fim": {"type": "short"},
                }},
                "qualidade": {"properties": {
                    "segmentacao_incerta": {"type": "boolean"},
                    "alternativas_incompletas": {"type": "boolean"},
                    "sem_gabarito": {"type": "boolean"},
                }},
                "extraido_em": {"type": "date"},
            },
        },
    }


def garantir_indice(es, recriar: bool = False) -> bool:
    """Cria o indice se nao existir. Retorna True se criou."""
    from elasticsearch import BadRequestError
    if recriar and es.indices.exists(index=config.ES_INDICE):
        es.indices.delete(index=config.ES_INDICE)
    if es.indices.exists(index=config.ES_INDICE):
        return False
    d = definicao()
    try:
        es.indices.create(index=config.ES_INDICE, settings=d["settings"], mappings=d["mappings"])
        return True
    except BadRequestError as e:  # outro processo criou ao mesmo tempo
        if "resource_already_exists" in str(e):
            return False
        raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mostrar", action="store_true")
    g.add_argument("--criar", action="store_true")
    g.add_argument("--recriar", action="store_true", help="APAGA o indice e recria")
    a = ap.parse_args(argv)
    if a.mostrar:
        print(json.dumps(definicao(), ensure_ascii=False, indent=2))
        return 0
    from elasticsearch import Elasticsearch
    es = Elasticsearch(config.ES_URL)
    criado = garantir_indice(es, recriar=a.recriar)
    print("indice criado" if criado else "indice ja existia")
    return 0


if __name__ == "__main__":
    sys.exit(main())
