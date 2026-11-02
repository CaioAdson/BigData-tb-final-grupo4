"""Produtor: le o manifesto, extrai as questoes e publica no Kafka (RF07).

Uso:
  python -m enade.produtor --manifest ../data/manifest.csv
  python -m enade.produtor --manifest ../data/manifest.csv --dry-run --saida saida.jsonl
  python -m enade.produtor --manifest ../data/manifest.csv --injetar-invalida   # testa a DLQ (RF11)
"""
import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .extrator import extrair_prova

log = logging.getLogger("produtor")


def ler_manifesto(caminho: Path):
    """Colunas: pdf_prova, pdf_gabarito, area, curso, ano, qtd_fg (opcional, padrao 8).
    Caminhos relativos ao diretorio do manifesto."""
    base = caminho.resolve().parent
    with open(caminho, newline="", encoding="utf-8") as f:
        for lin in csv.DictReader(f):
            if not lin.get("pdf_prova") or lin["pdf_prova"].startswith("#"):
                continue
            yield {
                "pdf_prova": base / lin["pdf_prova"].strip(),
                "pdf_gabarito": (base / lin["pdf_gabarito"].strip()) if lin.get("pdf_gabarito", "").strip() else None,
                "area": lin["area"].strip(), "curso": lin["curso"].strip(),
                "ano": int(lin["ano"]), "qtd_fg": int(lin.get("qtd_fg") or 8),
            }


def extrair_manifesto(caminho: Path, pasta_midia: Path | None):
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in ler_manifesto(caminho):
        if not item["pdf_prova"].exists():
            log.error("PDF nao encontrado: %s (pulando)", item["pdf_prova"])
            continue
        try:
            docs = extrair_prova(item["pdf_prova"], item["pdf_gabarito"], area=item["area"],
                                 curso=item["curso"], ano=item["ano"], qtd_fg=item["qtd_fg"],
                                 pasta_midia=pasta_midia)
        except Exception:
            log.exception("falha ao extrair %s (pulando)", item["pdf_prova"])
            continue
        for d in docs:
            d["extraido_em"] = agora
            yield d


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true", help="nao publica; so extrai")
    ap.add_argument("--saida", type=Path, help="com --dry-run, grava JSONL neste arquivo")
    ap.add_argument("--midia", type=Path, help="pasta para salvar recortes de imagens (opcional)")
    ap.add_argument("--injetar-invalida", action="store_true", help="publica 2 mensagens invalidas p/ testar DLQ")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    t0, total = time.time(), 0
    if args.dry_run:
        out = open(args.saida, "w", encoding="utf-8") if args.saida else sys.stdout
        for d in extrair_manifesto(args.manifest, args.midia):
            out.write(json.dumps(d, ensure_ascii=False) + "\n")
            total += 1
        if args.saida:
            out.close()
        log.info("dry-run: %d documentos", total)
        return 0

    from confluent_kafka import Producer  # import tardio: dry-run e testes nao exigem a lib
    erros = []

    def entrega(err, msg):
        if err:
            erros.append(str(err))

    prod = Producer({
        "bootstrap.servers": config.KAFKA_BOOTSTRAP,
        "acks": "all",                 # so confirma apos replicas sincronizadas
        "enable.idempotence": True,    # sem duplicatas por retry do produtor
        "compression.type": "lz4",
        "linger.ms": 20,
    })
    for d in extrair_manifesto(args.manifest, args.midia):
        while True:
            try:
                prod.produce(config.TOPICO_QUESTOES, key=d["id"], value=json.dumps(d, ensure_ascii=False), on_delivery=entrega)
                break
            except BufferError:
                prod.poll(0.5)
        prod.poll(0)
        total += 1
    if args.injetar_invalida:
        prod.produce(config.TOPICO_QUESTOES, key="invalida-json", value=b"{isto nao e json", on_delivery=entrega)
        prod.produce(config.TOPICO_QUESTOES, key="invalida-campos",
                     value=json.dumps({"id": "x", "curso": "Teste"}), on_delivery=entrega)
    prod.flush(60)
    dt = max(time.time() - t0, 1e-9)
    log.info("publicados %d documentos em %.1fs (%.1f docs/s); falhas de entrega: %d",
             total, dt, total / dt, len(erros))
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
