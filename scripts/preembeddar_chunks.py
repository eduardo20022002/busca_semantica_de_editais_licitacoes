"""Embedda de uma vez os Chunks de todos os editais selecionados de um dia,
com vários lotes em voo, populando o mesmo cache que a Análise profunda usa.

Por que existe: a Análise profunda chama o embedder uma vez por edital, e o
edital mediano cabe em UM lote — não há o que paralelizar dentro da chamada.
Medido em 2026-08-11: ~28s por lote, ~2 req/min, ~2h para 300 editais, com o
Tier 1 da Voyage ocioso (teto de 2.000 RPM). Juntando os Chunks de todos os
editais numa chamada só, os ~310 lotes passam a existir ao mesmo tempo e
podem ir concorrentes.

Não calcula Score nem escreve analise_profunda_*.json: só preenche o cache.
Depois disto, rodar cli_analise_profunda normalmente — ele encontra tudo em
cache e a fase de embedding sai de graça.

Uso: python scripts/preembeddar_chunks.py --data 2026-08-11
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from editais.transporte_voyage import MODELO_ANALISE_PROFUNDA, criar_embedder_voyage
from editais.triagem import criar_embedder_com_cache

DADOS = Path("dados")
DIRETORIO_CHUNKS = DADOS / "chunks"
CACHE_CHUNKS = DADOS / ".embeddings" / "chunks.jsonl"

# 8 lotes em voo com 3s de espaçamento: a partida fica em até 20 lotes/min,
# mas a latência real (~28s por lote) segura em ~17/min — ~4M TPM corrigindo
# pelo fator 2,61x de subestimação de tokens, metade do teto de 8M do Tier 1.
LOTES_SIMULTANEOS = 8
SEGUNDOS_ENTRE_LOTES = 3.0

# Uma chamada só, com dezenas de milhares de textos: o orçamento de tempo por
# chamada (240s, pensado para um edital) abortaria no meio, e persistir a cada
# 1.000 textos deixaria poucos lotes disponíveis por vez para paralelizar.
TEXTOS_POR_PERSISTENCIA = 5_000
SEM_ORCAMENTO_DE_TEMPO = float("inf")


def slug(numero: str) -> str:
    return numero.replace("/", "_").replace("\\", "_")


def carregar_chunks_dos_selecionados(data: str) -> list[str]:
    triagem = json.loads((DADOS / f"triagem_{data}.json").read_text(encoding="utf-8"))
    selecionados = [t for t in triagem if t.get("selecionado_para_analise_profunda")]
    selecionados.sort(key=lambda t: t["score_triagem"], reverse=True)

    vistos: set[str] = set()
    chunks: list[str] = []
    ausentes = 0
    for item in selecionados:
        caminho = DIRETORIO_CHUNKS / f"{slug(item['numeroControlePNCP'])}.json"
        if not caminho.exists():
            ausentes += 1
            continue
        for chunk in json.loads(caminho.read_text(encoding="utf-8")).get("chunks", []):
            # O mesmo trecho pode aparecer em editais diferentes; embeddar uma
            # vez só evita gastar lote com trabalho repetido.
            if chunk not in vistos:
                vistos.add(chunk)
                chunks.append(chunk)

    print(f"{len(selecionados)} editais selecionados ({ausentes} ainda sem chunks em disco)")
    print(f"{len(chunks)} chunks distintos a considerar", flush=True)
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Pré-embedda os Chunks do dia em paralelo.")
    parser.add_argument("--data", required=True, help="Data de referência (AAAA-MM-DD).")
    args = parser.parse_args()

    chunks = carregar_chunks_dos_selecionados(args.data)
    if not chunks:
        print("nada a fazer")
        return

    embedder_voyage = criar_embedder_voyage(
        modelo=MODELO_ANALISE_PROFUNDA,
        lotes_simultaneos=LOTES_SIMULTANEOS,
        segundos_entre_lotes=SEGUNDOS_ENTRE_LOTES,
    )
    embedder = criar_embedder_com_cache(
        embedder_voyage,
        CACHE_CHUNKS,
        MODELO_ANALISE_PROFUNDA,
        textos_por_persistencia=TEXTOS_POR_PERSISTENCIA,
        segundos_maximos_por_chamada=SEM_ORCAMENTO_DE_TEMPO,
    )

    print(
        f"embeddando com {LOTES_SIMULTANEOS} lotes simultâneos "
        f"({SEGUNDOS_ENTRE_LOTES}s de espaçamento)...",
        flush=True,
    )
    comeco = time.monotonic()
    embedder(chunks)
    decorrido = time.monotonic() - comeco

    print(f"concluído em {decorrido / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
