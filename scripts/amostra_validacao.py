#!/usr/bin/env python3
"""RNF03: sorteia >= 50 questoes extraidas para conferencia manual contra o PDF.
Uso:
  python -m enade.produtor --manifest data/manifest.csv --dry-run --saida extraidas.jsonl   (em ingestao/)
  python scripts/amostra_validacao.py extraidas.jsonl --n 50 --seed 42 > amostra.csv
Cada linha traz PDF e pagina para abrir o original; preencha as colunas 'ok_*' com S/N e
calcule a taxa de acerto (guarde a seed para o relatorio ser reprodutivel)."""
import argparse, csv, json, random, sys

ap = argparse.ArgumentParser()
ap.add_argument("jsonl"); ap.add_argument("--n", type=int, default=50); ap.add_argument("--seed", type=int, default=42)
a = ap.parse_args()
docs = [json.loads(l) for l in open(a.jsonl, encoding="utf-8")]
amostra = random.Random(a.seed).sample(docs, min(a.n, len(docs)))
w = csv.writer(sys.stdout)
w.writerow(["id", "pdf", "pagina", "tipo_questao", "gabarito", "n_alternativas", "alerta_qualidade",
            "enunciado_extraido", "ok_segmentacao", "ok_enunciado", "ok_alternativas", "ok_gabarito", "ok_midia", "obs"])
for d in amostra:
    w.writerow([d["id"], d["origem"]["pdf"], d["origem"]["pagina_inicio"], d["tipo_questao"], d["gabarito"],
                len(d["alternativas"]), any(d["qualidade"].values()), d["enunciado"][:200], "", "", "", "", "", ""])
