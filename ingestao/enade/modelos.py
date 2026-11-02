"""Modelo do documento 'questao', geracao de ID deterministico e validacao."""
import re
import unicodedata

TIPOS_PROVA = {"FG", "CE"}
TIPOS_QUESTAO = {"objetiva", "discursiva"}


def slug(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def gerar_id(curso: str, ano: int, tipo_prova: str, numero: int) -> str:
    """ID deterministico (RF10): reprocessar o mesmo PDF gera o mesmo _id,
    entao o Elasticsearch sobrescreve em vez de duplicar."""
    return f"{slug(curso)}-{ano}-{tipo_prova.lower()}-{numero:03d}"


def montar_texto_completo(doc: dict) -> str:
    partes = [doc.get("texto_base", ""), doc.get("enunciado", "")]
    partes += [a["texto"] for a in doc.get("alternativas", [])]
    return "\n".join(p for p in partes if p).strip()


def validar_documento(doc) -> list[str]:
    """Retorna lista de erros (vazia = valido). Usada pelo consumidor (RF11)."""
    if not isinstance(doc, dict):
        return ["documento nao e um objeto JSON"]
    erros = []

    def exige(campo, tipo, nao_vazio=False):
        v = doc.get(campo)
        if not isinstance(v, tipo) or isinstance(v, bool) and tipo is int:
            erros.append(f"campo '{campo}' ausente ou com tipo invalido")
        elif nao_vazio and not v:
            erros.append(f"campo '{campo}' vazio")
        return v

    exige("id", str, True)
    exige("area", str, True)
    exige("curso", str, True)
    ano = exige("ano", int)
    if isinstance(ano, int) and not 2004 <= ano <= 2100:
        erros.append("ano fora do intervalo 2004-2100")
    if doc.get("tipo_prova") not in TIPOS_PROVA:
        erros.append("tipo_prova deve ser FG ou CE")
    if doc.get("tipo_questao") not in TIPOS_QUESTAO:
        erros.append("tipo_questao deve ser objetiva ou discursiva")
    num = exige("numero", int)
    if isinstance(num, int) and num <= 0:
        erros.append("numero deve ser positivo")
    exige("anulada", bool)
    exige("texto_completo", str, True)
    origem = doc.get("origem")
    if not isinstance(origem, dict) or not origem.get("pdf") or not isinstance(origem.get("pagina_inicio"), int):
        erros.append("origem (pdf + pagina_inicio) obrigatoria (RF06)")
    return erros
