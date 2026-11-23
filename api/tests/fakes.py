"""Dublês de teste: Elasticsearch em memoria e servidor LDAP mock (ldap3 MOCK_SYNC).

O FakeES interpreta o subconjunto de Query DSL que a API gera (bool/filter/term/exists,
multi_match, match_phrase, terms/filter aggs, highlight, from/size) com um "stemming"
simplificado (prefixo de 5 letras sem acento). A relevancia real em portugues e validada
nos testes de integracao com Elasticsearch de verdade (test_integracao_es.py).
"""
import copy
import re
import unicodedata

from elasticsearch import NotFoundError
from ldap3 import MOCK_SYNC, OFFLINE_SLAPD_2_4, Server

QUESTOES = [
    {"id": "si-2021-fg-001", "area": "Computação", "curso": "Sistemas de Informação", "ano": 2021,
     "tipo_prova": "FG", "tipo_questao": "objetiva", "numero": 1, "anulada": False,
     "texto_base": "A ética profissional orienta condutas.", "enunciado": "Sobre ética e cidadania, assinale a correta.",
     "alternativas": [{"letra": "A", "texto": "Moral é individual."}, {"letra": "B", "texto": "Ética é coletiva."}],
     "gabarito": "B", "competencias": ["Ética"], "objetos_conhecimento": [],
     "qualidade": {"sem_gabarito": False}},
    {"id": "si-2021-ce-009", "area": "Computação", "curso": "Sistemas de Informação", "ano": 2021,
     "tipo_prova": "CE", "tipo_questao": "objetiva", "numero": 9, "anulada": False,
     "enunciado": "Analise os algoritmos de ordenação a seguir.",
     "alternativas": [{"letra": "A", "texto": "Quicksort é estável."}, {"letra": "B", "texto": "Mergesort é O(n log n)."}],
     "gabarito": "B", "competencias": ["Raciocínio lógico", "Algoritmos"], "objetos_conhecimento": ["Ordenação"]},
    {"id": "si-2023-ce-010", "area": "Computação", "curso": "Sistemas de Informação", "ano": 2023,
     "tipo_prova": "CE", "tipo_questao": "objetiva", "numero": 10, "anulada": True,
     "enunciado": "Um algoritmo guloso resolve o problema da mochila fracionária?",
     "alternativas": [{"letra": "A", "texto": "Sim."}, {"letra": "B", "texto": "Não."}],
     "gabarito": None, "competencias": ["Algoritmos"], "objetos_conhecimento": []},
    {"id": "cc-2023-ce-011", "area": "Computação", "curso": "Ciência da Computação", "ano": 2023,
     "tipo_prova": "CE", "tipo_questao": "discursiva", "numero": 11, "anulada": False,
     "enunciado": "Descreva a complexidade de algoritmos de busca em grafos.",
     "alternativas": [], "gabarito": None, "competencias": ["Raciocínio lógico"], "objetos_conhecimento": []},
    {"id": "enf-2022-fg-002", "area": "Saúde", "curso": "Enfermagem", "ano": 2022,
     "tipo_prova": "FG", "tipo_questao": "objetiva", "numero": 2, "anulada": False,
     "enunciado": "Sobre políticas públicas de saúde, assinale a alternativa correta.",
     "alternativas": [{"letra": "A", "texto": "O SUS é universal."}, {"letra": "B", "texto": "O SUS é privado."}],
     "gabarito": "A", "competencias": [], "objetos_conhecimento": []},
]


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def _raiz(token: str) -> str:
    return token[:5]


STOP = {"a", "o", "e", "de", "da", "do", "em", "os", "as", "para", "sobre", "um", "uma"}


def _tokens(t: str) -> list[str]:
    return [_raiz(x) for x in re.findall(r"\w+", _norm(t)) if x not in STOP]


def _valor(doc: dict, campo: str):
    atual = doc
    for parte in campo.split("."):
        if isinstance(atual, list):
            return [x.get(parte) for x in atual if isinstance(x, dict)]
        atual = (atual or {}).get(parte)
    return atual


def _lista(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _textos(doc: dict, campo: str) -> list[str]:
    campo = campo.split("^")[0]
    if campo == "texto_completo":
        partes = [doc.get("texto_base") or "", doc.get("enunciado") or ""] + [a["texto"] for a in doc.get("alternativas", [])]
        return ["\n".join(partes)]
    if campo == "curso.texto":
        return [doc.get("curso") or ""]
    return [str(x) for x in _lista(_valor(doc, campo)) if x]


def _casa(doc: dict, consulta: dict) -> bool:
    if "match_all" in consulta:
        return True
    if "term" in consulta:
        campo, valor = next(iter(consulta["term"].items()))
        if isinstance(valor, dict):
            valor = valor["value"]
        return valor in _lista(_valor(doc, campo))
    if "exists" in consulta:
        return bool([x for x in _lista(_valor(doc, consulta["exists"]["field"])) if x not in (None, "")])
    if "bool" in consulta:
        b = consulta["bool"]
        return all(_casa(doc, f) for f in b.get("filter", []) + b.get("must", []))
    if "multi_match" in consulta:
        mm = consulta["multi_match"]
        termos = set(_tokens(mm["query"]))
        presentes = set()
        for campo in mm["fields"]:
            for t in _textos(doc, campo):
                presentes |= termos & set(_tokens(t))
        return len(presentes) >= max(1, int(len(termos) * 0.75))
    if "match_phrase" in consulta:
        return True
    raise NotImplementedError(consulta)


def _destacar(texto: str, termos: set[str]) -> str | None:
    achou = False

    def troca(m):
        nonlocal achou
        if _raiz(_norm(m.group(0))) in termos:
            achou = True
            return f"<mark>{m.group(0)}</mark>"
        return m.group(0)
    saida = re.sub(r"\w+", troca, texto)
    return saida if achou else None


def _agregar(docs: list[dict], aggs: dict) -> dict:
    saida = {}
    for nome, definicao in aggs.items():
        sub = definicao.get("aggs")
        if "terms" in definicao:
            campo = definicao["terms"]["field"]
            grupos: dict = {}
            for d in docs:
                for v in set(_lista(_valor(d, campo))):
                    if v is not None:
                        grupos.setdefault(v, []).append(d)
            ordem = definicao["terms"].get("order", {})
            itens = sorted(grupos.items(), key=(lambda kv: kv[0]) if "_key" in ordem else (lambda kv: (-len(kv[1]), str(kv[0]))))
            buckets = []
            for k, ds in itens[: definicao["terms"].get("size", 10)]:
                b = {"key": k, "doc_count": len(ds)}
                if sub:
                    b.update(_agregar(ds, sub))
                buckets.append(b)
            saida[nome] = {"buckets": buckets}
        elif "filter" in definicao:
            ds = [d for d in docs if _casa(d, definicao["filter"])]
            saida[nome] = {"doc_count": len(ds), **(_agregar(ds, sub) if sub else {})}
    return saida


class FakeES:
    def __init__(self, docs=None, indice_existe=True):
        self.docs = {d["id"]: copy.deepcopy(d) for d in (docs if docs is not None else QUESTOES)}
        self.indice_existe = indice_existe
        self.chamadas: list[dict] = []
        self.falhar: Exception | None = None

    def _checar(self):
        if self.falhar:
            raise self.falhar
        if not self.indice_existe:
            raise NotFoundError("index_not_found_exception", meta=_Meta(404), body={"error": {"type": "index_not_found_exception"}})

    async def ping(self):
        return self.falhar is None

    async def search(self, index, query=None, size=10, from_=0, aggs=None, highlight=None, sort=None,
                     source=None, track_total_hits=None):
        self.chamadas.append({"index": index, "query": query, "size": size, "from_": from_, "aggs": aggs,
                              "highlight": highlight, "sort": sort})
        self._checar()
        docs = [d for d in self.docs.values() if _casa(d, query or {"match_all": {}})]
        docs.sort(key=lambda d: (-d["ano"], d["id"]))
        hits = []
        termos = set()
        if highlight and query and query["bool"].get("must") and "multi_match" in query["bool"]["must"][0]:
            termos = set(_tokens(query["bool"]["must"][0]["multi_match"]["query"]))
        for d in docs[from_: from_ + size]:
            h = {"_id": d["id"], "_source": copy.deepcopy(d)}
            if termos:
                hl = {}
                for campo in highlight["fields"]:
                    frags = [x for x in (_destacar(t, termos) for t in _textos(d, campo)) if x]
                    if frags:
                        hl[campo] = frags
                if hl:
                    h["highlight"] = hl
            hits.append(h)
        resposta = {"hits": {"total": {"value": len(docs), "relation": "eq"}, "hits": hits}}
        if aggs:
            resposta["aggregations"] = _agregar(docs, aggs)
        return resposta

    async def get(self, index, id, source_includes=None):
        self._checar()
        if id not in self.docs:
            raise NotFoundError("not_found", meta=_Meta(404), body={"found": False})
        return {"_id": id, "found": True, "_source": copy.deepcopy(self.docs[id])}

    async def mget(self, index, ids, source_includes=None):
        self._checar()
        return {"docs": [{"_id": i, "found": i in self.docs, **({"_source": copy.deepcopy(self.docs[i])} if i in self.docs else {})}
                         for i in ids]}

    async def close(self):
        pass


class _Meta:
    def __init__(self, status):
        self.status = status
        self.headers = {}
        self.http_version = "1.1"
        self.duration = 0
        self.node = None


# ------------------------------------------------------------------ LDAP
BASE = "dc=enade,dc=local"
SENHAS = {"prof.ana": "senha-prof-teste", "aluno.bruno": "senha-aluno-teste", "visitante": "senha-visit-teste"}


def servidor_ldap_mock():
    """Servidor LDAP em memoria com usuarios e grupos iguais aos do seed (infra/ldap)."""
    servidor = Server("mock_enade", get_info=OFFLINE_SLAPD_2_4)
    from ldap3 import Connection
    conn = Connection(servidor, user=f"cn=admin,{BASE}", password="admin-teste", client_strategy=MOCK_SYNC)
    conn.strategy.add_entry(f"cn=admin,{BASE}", {"objectClass": ["person"], "userPassword": "admin-teste", "cn": "admin", "sn": "admin"})
    usuarios = {"prof.ana": "Ana Professora", "aluno.bruno": "Bruno Estudante", "visitante": "Visitante Sem Grupo"}
    for uid, nome in usuarios.items():
        conn.strategy.add_entry(f"uid={uid},ou=usuarios,{BASE}", {
            "objectClass": ["inetOrgPerson"], "uid": uid, "cn": nome, "sn": nome.split()[-1],
            "displayName": nome, "userPassword": SENHAS[uid]})
    conn.strategy.add_entry(f"cn=professores,ou=grupos,{BASE}", {
        "objectClass": ["groupOfNames"], "cn": "professores", "member": [f"uid=prof.ana,ou=usuarios,{BASE}"]})
    conn.strategy.add_entry(f"cn=estudantes,ou=grupos,{BASE}", {
        "objectClass": ["groupOfNames"], "cn": "estudantes", "member": [f"uid=aluno.bruno,ou=usuarios,{BASE}"]})
    return servidor
