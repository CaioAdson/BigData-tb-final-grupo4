"""Exportacao do carrinho como simulado (JSON e PDF).

Preserva texto-base, enunciado e alternativas exatamente como indexados, inclui os
metadados de cada questao e so inclui gabaritos quando `incluir_gabarito=True`
(a rota decide isso pelo perfil do usuario).
"""
import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def montar_simulado(questoes: list[dict], usuario: dict, incluir_gabarito: bool) -> dict:
    itens = []
    for ordem, q in enumerate(questoes, start=1):
        item = {"ordem": ordem, **q}
        if not incluir_gabarito:
            item["gabarito"] = None
        itens.append(item)
    return {
        "titulo": "Simulado ENADE",
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gerado_por": {"id": usuario["id"], "nome": usuario["nome"], "perfil": usuario["perfil"]},
        "inclui_gabarito": incluir_gabarito,
        "total_questoes": len(itens),
        "questoes": itens,
        "gabarito": ([{"ordem": i["ordem"], "id": i["id"], "gabarito": i["gabarito"], "anulada": i["anulada"]}
                      for i in itens] if incluir_gabarito else None),
    }


def _p(texto: str | None) -> str:
    """Escapa para o mini-HTML do ReportLab preservando quebras de linha."""
    return escape(texto or "").replace("\n", "<br/>")


def gerar_pdf(simulado: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title=simulado["titulo"], author=simulado["gerado_por"]["nome"])
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=estilos["Title"], alignment=TA_CENTER)
    meta = ParagraphStyle("meta", parent=estilos["Normal"], fontSize=8, textColor=colors.grey, leading=10)
    corpo = ParagraphStyle("corpo", parent=estilos["Normal"], fontSize=10, leading=14, spaceAfter=6)
    alt = ParagraphStyle("alt", parent=corpo, leftIndent=14, spaceAfter=3)
    cab = ParagraphStyle("cab", parent=estilos["Heading3"], spaceBefore=10, spaceAfter=4)

    historia = [
        Paragraph(_p(simulado["titulo"]), titulo),
        Paragraph(_p(f"Gerado em {simulado['gerado_em']} por {simulado['gerado_por']['nome']} "
                     f"({simulado['gerado_por']['perfil']}) - {simulado['total_questoes']} questões"), meta),
        Spacer(1, 12),
    ]
    for q in simulado["questoes"]:
        bloco = [
            Paragraph(_p(f"Questão {q['ordem']}"), cab),
            Paragraph(_p(f"{q['area']} | {q['curso']} | ENADE {q['ano']} | {q['tipo_prova']} | "
                         f"nº {q['numero']} | {q['tipo_questao']}"
                         + (" | ANULADA" if q.get("anulada") else "")
                         + (f" | Competências: {', '.join(q['competencias'])}" if q.get("competencias") else "")
                         + f" | id: {q['id']}"), meta),
            Spacer(1, 4),
        ]
        if q.get("texto_base"):
            bloco.append(Paragraph(_p(q["texto_base"]), corpo))
        bloco.append(Paragraph(_p(q["enunciado"]), corpo))
        historia.append(KeepTogether(bloco))
        for a in q.get("alternativas") or []:
            historia.append(Paragraph(f"<b>{escape(a['letra'])})</b> {_p(a['texto'])}", alt))
        if q["tipo_questao"] == "discursiva":
            historia.append(Paragraph("<i>Questão discursiva: responda no espaço próprio.</i>", meta))
    if simulado.get("gabarito"):
        historia += [PageBreak(), Paragraph("Gabarito", titulo), Spacer(1, 8)]
        linhas = [["Questão", "Identificador", "Resposta"]]
        for g in simulado["gabarito"]:
            resposta = "Anulada" if g["anulada"] else (g["gabarito"] or "—")
            linhas.append([str(g["ordem"]), g["id"], resposta])
        tabela = Table(linhas, colWidths=[2.5 * cm, 10 * cm, 3 * cm])
        tabela.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        historia.append(tabela)
    doc.build(historia)
    return buffer.getvalue()
