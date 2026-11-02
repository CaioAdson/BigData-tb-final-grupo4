"""Extracao de provas e gabaritos do ENADE (PDF -> documentos por questao).

Estrategia (heuristica, validar em amostra manual >= 50 questoes, RNF03):
  1. Le o PDF linha a linha com pdfplumber, guardando pagina e posicao vertical.
  2. Segmenta por cabecalhos 'QUESTAO NN' / 'QUESTAO DISCURSIVA NN'.
  3. Em cada bloco separa texto-base, enunciado e alternativas A-E.
  4. Cruza com o gabarito (PDF separado); 'Anulada' vira anulada=True (RF03).
  5. Imagens ficam como midia pendente (LLM na semana 3); tabelas viram Markdown.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from .modelos import gerar_id, montar_texto_completo

log = logging.getLogger("extrator")

RE_CABECALHO = re.compile(r"^\s*QUEST[ÃA]O\s+(DISCURSIVA\s+)?(\d{1,2})\s*(\(.*\))?\s*$")
RE_FIM = re.compile(r"QUESTION[ÁA]RIO\s+DE\s+PERCEP[ÇC][ÃA]O", re.I)
RE_ALT = re.compile(r"^\(?([A-E])(?:\)|\.|\s|$)\s*(.*)$")
RE_COMANDO = re.compile(
    r"^(Com base|Considerando|A partir|Assinale|Analise|Em rela[çc][ãa]o|Diante|De acordo|"
    r"Nesse contexto|Nesse sentido|Tendo em vista|Sobre|Acerca|[ÉE] correto|Julgue|Avalie|"
    r"Identifique|Qual|Quais|Como|Escreva|Elabore|Redija|Justifique|Explique|Apresente)\b"
)
RE_FIM_FRASE = re.compile(r"[.!?:;»”\"]\s*$")
RUIDO_PADRAO = [
    re.compile(r"^\s*[ÁA]REA\s+LIVRE\s*$", re.I),
    re.compile(r"^\s*\*[A-Z0-9]{6,}\*\s*$"),  # codigos de barra/versao no rodape
]
RE_GAB = re.compile(r"\b(\d{1,2})\b\s*[-–:.)]?\s*(ANULAD[AO]|Anulad[ao]|[A-E])\b")


@dataclass
class Linha:
    texto: str
    pagina: int
    top: float


# ---------------------------------------------------------------- leitura
def _ruido(texto: str, extra=()) -> bool:
    return any(r.match(texto) for r in (*RUIDO_PADRAO, *extra))


def ler_linhas(pdf, ruido_extra=()) -> list[Linha]:
    linhas = []
    for i, page in enumerate(pdf.pages, start=1):
        for l in page.extract_text_lines(strip=True):
            t = l["text"].strip()
            if t and not _ruido(t, ruido_extra):
                linhas.append(Linha(t, i, float(l["top"])))
    return linhas


def tabela_para_markdown(linhas_tabela) -> str:
    rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in linhas_tabela if r]
    if len(rows) < 2 or not rows[0]:
        return ""
    cab = "| " + " | ".join(rows[0]) + " |"
    sep = "|" + "|".join(["---"] * len(rows[0])) + "|"
    corpo = ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join([cab, sep, *corpo])


# ------------------------------------------------------------ segmentacao
def segmentar(linhas: list[Linha]):
    """Retorna lista de (numero, discursiva, ini, fim) com indices em 'linhas' (fim exclusivo)."""
    cabs, limite = [], len(linhas)
    for idx, l in enumerate(linhas):
        if RE_FIM.search(l.texto):
            limite = idx
            break
        m = RE_CABECALHO.match(l.texto)
        if m:
            cabs.append((idx, int(m.group(2)), bool(m.group(1))))
    blocos, vistos = [], set()
    for k, (idx, num, disc) in enumerate(cabs):
        fim = cabs[k + 1][0] if k + 1 < len(cabs) else limite
        if num in vistos:
            log.warning("questao %s duplicada no PDF; mantendo a primeira ocorrencia", num)
            continue
        vistos.add(num)
        blocos.append((num, disc, idx, fim))
    return blocos


def parse_bloco(textos: list[str], discursiva: bool) -> dict:
    """Separa texto_base / enunciado / alternativas de um bloco de linhas (sem o cabecalho)."""
    alternativas, corpo, incerta = [], list(textos), False

    if not discursiva:
        cand = [(i, m.group(1)) for i, t in enumerate(textos) if (m := RE_ALT.match(t))]
        seq = None
        for pos in range(len(cand) - 1, -1, -1):  # ultimo 'A' com B..E depois dele
            if cand[pos][1] != "A":
                continue
            achados, p = [cand[pos]], pos
            for letra in "BCDE":
                nxt = next((c for c in cand[p + 1:] if c[1] == letra), None)
                if not nxt:
                    break
                achados.append(nxt)
                p = cand.index(nxt)
            if len(achados) == 5:
                seq = achados
                break
        if seq:
            corpo = textos[: seq[0][0]]
            for n, (i, letra) in enumerate(seq):
                fim = seq[n + 1][0] if n + 1 < len(seq) else len(textos)
                primeira = RE_ALT.match(textos[i]).group(2).strip()
                resto = [primeira, *textos[i + 1: fim]]
                alternativas.append({"letra": letra, "texto": " ".join(x for x in resto if x).strip()})

    # enunciado = a partir do ultimo "comando" que inicia uma frase nova
    corte = None
    for j in range(len(corpo) - 1, -1, -1):
        if RE_COMANDO.match(corpo[j]) and (j == 0 or RE_FIM_FRASE.search(corpo[j - 1])):
            corte = j
            break
    if corte is None:
        base, enun, incerta = [], corpo, True
    else:
        base, enun = corpo[:corte], corpo[corte:]
    return {
        "texto_base": " ".join(base).strip(),
        "enunciado": " ".join(enun).strip(),
        "alternativas": alternativas,
        "segmentacao_incerta": incerta,
    }


# --------------------------------------------------------------- gabarito
def ler_gabarito(caminho: Path) -> dict[int, str]:
    """numero -> 'A'..'E' ou 'ANULADA'. Regex tolerante; conferir contra o PDF real."""
    with pdfplumber.open(caminho) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
    gab = {}
    for num, resp in RE_GAB.findall(texto):
        r = "ANULADA" if resp.upper().startswith("ANULAD") else resp.upper()
        gab.setdefault(int(num), r)
    return gab


# ------------------------------------------------------------------ midia
def _bloco_da_posicao(linhas, blocos_por_linha, pagina, y):
    na_pagina = [i for i, l in enumerate(linhas) if l.pagina == pagina]
    if not na_pagina:
        return None
    ant = [i for i in na_pagina if linhas[i].top <= y]
    if ant:
        return blocos_por_linha[ant[-1]]
    return blocos_por_linha[na_pagina[0] - 1] if na_pagina[0] > 0 else blocos_por_linha[na_pagina[0]]


def coletar_midia(pdf, linhas, blocos, pasta_midia: Path | None, prefixo: str):
    """Retorna dict numero -> lista de midias. Imagens: status 'pendente'. Tabelas: Markdown."""
    por_linha = [None] * len(linhas)
    for num, _, ini, fim in blocos:
        for i in range(ini, fim):
            por_linha[i] = num
    saida: dict[int, list] = {}
    for np_, page in enumerate(pdf.pages, start=1):
        itens = []
        for img in page.images:
            if (img["x1"] - img["x0"]) >= 15 and (img["bottom"] - img["top"]) >= 15:
                itens.append(("imagem", (img["x0"], img["top"], img["x1"], img["bottom"]), None))
        try:
            for t in page.find_tables():
                md = tabela_para_markdown(t.extract())
                if md:
                    itens.append(("tabela", t.bbox, md))
        except Exception as e:  # tabela mal formada nao pode derrubar a extracao
            log.debug("find_tables falhou na pagina %s: %s", np_, e)
        for tipo, bbox, md in itens:
            num = _bloco_da_posicao(linhas, por_linha, np_, bbox[1])
            if num is None:
                continue
            lista = saida.setdefault(num, [])
            item = {"tipo": tipo, "pagina": np_, "bbox": [round(x, 1) for x in bbox]}
            if tipo == "tabela":
                item.update(formato="markdown", conteudo=md, status="ok")
            else:
                item.update(formato=None, conteudo=None, status="pendente")
                if pasta_midia:
                    try:
                        pasta_midia.mkdir(parents=True, exist_ok=True)
                        arq = pasta_midia / f"{prefixo}-q{num:03d}-{len(lista) + 1}.png"
                        b = (max(bbox[0], 0), max(bbox[1], 0), min(bbox[2], page.width), min(bbox[3], page.height))
                        page.crop(b).to_image(resolution=150).save(str(arq))
                        item["arquivo"] = str(arq)
                    except Exception as e:
                        log.warning("nao foi possivel salvar recorte (%s)", e)
            lista.append(item)
    return saida


# ------------------------------------------------------------- orquestracao
def extrair_prova(pdf_prova: Path, pdf_gabarito: Path | None, *, area: str, curso: str,
                  ano: int, qtd_fg: int = 8, pasta_midia: Path | None = None) -> list[dict]:
    gabarito = ler_gabarito(pdf_gabarito) if pdf_gabarito and Path(pdf_gabarito).exists() else {}
    docs = []
    with pdfplumber.open(pdf_prova) as pdf:
        linhas = ler_linhas(pdf)
        blocos = segmentar(linhas)
        midia = coletar_midia(pdf, linhas, blocos, pasta_midia, f"{ano}-{Path(pdf_prova).stem}")
    for num, disc, ini, fim in blocos:
        corpo = linhas[ini + 1: fim]
        p = parse_bloco([l.texto for l in corpo], disc)
        tipo_prova = "FG" if num <= qtd_fg else "CE"
        resp = gabarito.get(num)
        anulada = resp == "ANULADA"
        doc = {
            "id": gerar_id(curso, ano, tipo_prova, num),
            "area": area, "curso": curso, "ano": ano,
            "tipo_prova": tipo_prova,
            "tipo_questao": "discursiva" if disc else "objetiva",
            "numero": num,
            "anulada": anulada,
            "texto_base": p["texto_base"], "enunciado": p["enunciado"],
            "alternativas": p["alternativas"],
            "gabarito": None if (anulada or disc) else resp,
            "competencias": [], "objetos_conhecimento": [],  # semana 3: diretrizes/padrao de resposta
            "midia": midia.get(num, []),
            "origem": {
                "pdf": Path(pdf_prova).name,
                "pagina_inicio": linhas[ini].pagina,
                "pagina_fim": linhas[fim - 1].pagina,
            },
            "texto_bruto": "\n".join(l.texto for l in corpo),
        }
        doc["midia_pendente"] = any(m["status"] == "pendente" for m in doc["midia"])
        doc["texto_completo"] = montar_texto_completo(doc) or doc["texto_bruto"] or f"questao {num}"
        doc["qualidade"] = {
            "segmentacao_incerta": p["segmentacao_incerta"],
            "alternativas_incompletas": (not disc) and len(p["alternativas"]) != 5,
            "sem_gabarito": (not disc) and not anulada and resp is None,
        }
        docs.append(doc)
    log.info("%s: %d questoes extraidas (%d com alerta de qualidade)", Path(pdf_prova).name, len(docs),
             sum(any(d["qualidade"].values()) for d in docs))
    return docs
