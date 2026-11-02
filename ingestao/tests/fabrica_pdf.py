"""Gera PDFs SINTETICOS (nao sao dados do ENADE) para testes e para demonstrar o pipeline
sem depender do acervo real. Requer reportlab (requirements-dev.txt)."""
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ALT = lambda letra, t: f"{letra}  {t}"


def _escreve(c, y, linhas, passo=16):
    for l in linhas:
        c.drawString(60, y, l)
        y -= passo
    return y


def gerar_prova(caminho: Path):
    c = canvas.Canvas(str(caminho), pagesize=A4)
    H = A4[1]
    y = H - 60
    # ---------------- Q1 (objetiva, armadilhas: linhas que comecam com "A ")
    y = _escreve(c, y, [
        "QUESTÃO 01",
        "A ética profissional é tema recorrente nas organizações contemporâneas.",
        "Disponível em: www.exemplo.org. Acesso em: 1 jan. 2021.",
        "Com base no texto apresentado, assinale a alternativa correta.",
        "A respeito de condutas aceitáveis.",
        ALT("A", "Condutas éticas dependem apenas da lei."),
        ALT("B", "A moral individual é irrelevante."),
        ALT("C", "Códigos de ética orientam decisões coletivas."),
        ALT("D", "A ética não se aplica à tecnologia."),
        ALT("E", "Somente gestores respondem por condutas."),
        "*R012021A*",
    ])
    y -= 20
    # ---------------- Q2 (objetiva com imagem)
    y = _escreve(c, y, ["QUESTÃO 02", "Observe a figura a seguir."])
    img = Image.new("RGB", (160, 90), (200, 60, 60))
    c.drawImage(ImageReader(img), 60, y - 95, width=160, height=90)
    y -= 115
    y = _escreve(c, y, [
        "Considerando a figura, é correto afirmar que:",
        ALT("A", "o fluxo e unidirecional."), ALT("B", "o sistema e distribuido."),
        ALT("C", "nao ha persistencia."), ALT("D", "nao ha filas."), ALT("E", "ha apenas um no."),
    ])
    c.showPage()
    # ---------------- Q3 (discursiva com tabela)
    y = H - 60
    y = _escreve(c, y, [
        "QUESTÃO DISCURSIVA 03",
        "A tabela mostra o desempenho de dois sistemas de busca.",
    ])
    x0, w, h = 60, 90, 18
    dados = [["Sistema", "p95 (ms)", "Docs/s"], ["Alfa", "420", "900"], ["Beta", "610", "450"]]
    top = y - 5
    for r, linha in enumerate(dados):
        for k, cel in enumerate(linha):
            c.rect(x0 + k * w, top - (r + 1) * h, w, h)
            c.drawString(x0 + k * w + 4, top - (r + 1) * h + 5, cel)
    y = top - len(dados) * h - 25
    y = _escreve(c, y, [
        "Fonte: elaboracao propria.",
        "Redija um texto discutindo qual sistema atende melhor um requisito de latencia.",
    ])
    y -= 20
    # ---------------- Q4 (objetiva anulada)
    y = _escreve(c, y, [
        "QUESTÃO 04", "O enunciado desta questao continha erro de impressao.",
        "Assinale a alternativa correta.",
        ALT("A", "primeira"), ALT("B", "segunda"), ALT("C", "terceira"), ALT("D", "quarta"), ALT("E", "quinta"),
    ])
    c.showPage()
    # ---------------- apos o fim, deve ser ignorado
    y = H - 60
    _escreve(c, y, ["QUESTIONÁRIO DE PERCEPÇÃO SOBRE A PROVA", "QUESTÃO 01", "Como voce avalia esta prova?"])
    c.showPage()
    c.save()


def gerar_gabarito(caminho: Path):
    c = canvas.Canvas(str(caminho), pagesize=A4)
    _escreve(c, A4[1] - 60, ["GABARITO ENADE 2021", "01 C", "02 B", "04 Anulada"])
    c.showPage()
    c.save()


def gerar_demo(pasta: Path, curso="Sistemas de Informação Demo", area="Computação", ano=2021):
    """Cria PDFs sinteticos + manifest.csv em 'pasta'."""
    pasta.mkdir(parents=True, exist_ok=True)
    gerar_prova(pasta / "demo_prova.pdf")
    gerar_gabarito(pasta / "demo_gabarito.pdf")
    (pasta / "manifest.csv").write_text(
        "pdf_prova,pdf_gabarito,area,curso,ano,qtd_fg\n"
        f"demo_prova.pdf,demo_gabarito.pdf,{area},{curso},{ano},3\n", encoding="utf-8")
    return pasta / "manifest.csv"
