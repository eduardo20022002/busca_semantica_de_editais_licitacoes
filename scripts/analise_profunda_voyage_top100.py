"""Análise profunda completa dos 100 editais de teste, usando a Voyage
(voyage-4, Tier 1) — mesmo embedder e caches de produção usados por
cli_analise_profunda.py, aplicado à base local em dados/chunks/ (já
regenerada com o filtro Edital/TR + fallback hierárquico).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from editais.analise_profunda import ScoreAderencia, calcular_scores_aderencia
from editais.prioridade import carregar_perfil_prioridade
from editais.transporte_voyage import MODELO_ANALISE_PROFUNDA, criar_embedder_voyage
from editais.triagem import carregar_perfil, criar_embedder_com_cache

DADOS = Path("dados")
DIRETORIO_CHUNKS = DADOS / "chunks"
DIRETORIO_PERFIL = Path("perfil/produtos-aurora")
DIRETORIO_PERFIL_PRIORIDADE = Path("perfil/prioridade")
CACHE_CHUNKS = DADOS / ".embeddings" / "chunks.json"  # mesmo cache de produção
SAIDA = DADOS / "analise_profunda_voyage_top100.json"


def main() -> None:
    embedder = criar_embedder_voyage(modelo=MODELO_ANALISE_PROFUNDA)
    perfil = carregar_perfil(
        DIRETORIO_PERFIL, embedder, MODELO_ANALISE_PROFUNDA
    )
    perfil_prioridade = carregar_perfil_prioridade(
        DIRETORIO_PERFIL_PRIORIDADE, embedder, MODELO_ANALISE_PROFUNDA
    )
    embedder_de_chunks = criar_embedder_com_cache(
        embedder, CACHE_CHUNKS, MODELO_ANALISE_PROFUNDA
    )

    caminhos = sorted(DIRETORIO_CHUNKS.glob("*.json"))
    print(f"{len(caminhos)} editais a processar.\n", flush=True)

    scores: list[ScoreAderencia] = []
    pulados = 0
    inicio = time.monotonic()
    for posicao, caminho in enumerate(caminhos, start=1):
        numero = caminho.stem.replace("_", "/")
        chunks = json.loads(caminho.read_text(encoding="utf-8")).get("chunks", [])
        print(f"[{posicao}/{len(caminhos)}] {numero} ({len(chunks)} chunks)...", flush=True)

        scores_do_edital = calcular_scores_aderencia(
            {numero: chunks}, embedder_de_chunks, perfil, perfil_prioridade
        )
        if not scores_do_edital:
            pulados += 1
            print("  [pulado] falha persistente de embedding", flush=True)
        scores.extend(scores_do_edital)

    decorrido = time.monotonic() - inicio
    ordenados = sorted(scores, key=lambda s: s.score_aderencia, reverse=True)

    SAIDA.write_text(
        json.dumps(
            [
                {
                    "numeroControlePNCP": s.numero_controle_pncp,
                    "score_aderencia": s.score_aderencia,
                    "produto_mais_proximo": s.produto_mais_proximo,
                }
                for s in ordenados
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{'=' * 60}", flush=True)
    print(f"processados: {len(scores)} | pulados: {pulados}", flush=True)
    print(f"tempo total: {decorrido / 60:.1f} min", flush=True)
    print("\nTop-10 por Score de aderência:", flush=True)
    for s in ordenados[:10]:
        print(f"  {s.score_aderencia:.4f}  {s.produto_mais_proximo:<28} {s.numero_controle_pncp}", flush=True)
    print(f"\nsaída: {SAIDA}", flush=True)


if __name__ == "__main__":
    main()
