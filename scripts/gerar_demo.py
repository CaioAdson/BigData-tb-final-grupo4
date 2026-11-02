#!/usr/bin/env python3
"""Gera PDFs sinteticos + manifesto em data/demo/ para testar o pipeline sem o acervo real.
Uso (na raiz do repo, com reportlab instalado): python scripts/gerar_demo.py"""
import sys
from pathlib import Path

raiz = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz / "ingestao"))
from tests.fabrica_pdf import gerar_demo  # noqa: E402

print("manifesto:", gerar_demo(raiz / "data" / "demo"))
print("Publicar: docker compose run --rm produtor --manifest /data/demo/manifest.csv")
