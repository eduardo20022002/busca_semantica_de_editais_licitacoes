"""Compara o Perfil Aurora V4 contra a base de teste de 8.556 editais já
embeddados (base-teste/editais-embeddados_2026-07-0[6-10].json).

Não chama a API da Voyage: reaproveita o cache local do Perfil V4
(perfil/produtos-aurora/.embeddings/*.json) e os embeddings de objetoCompra já
gravados na base de teste. Só matemática (numpy) local.

Uso (rodar da raiz do repo):
    PYTHONPATH=src uv run python scripts/comparar_v4.py [N]
      N  tamanho do top a salvar; padrão 100
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from editais.triagem import carregar_perfil, similaridade_cosseno  # noqa: E402
from editais.transporte_voyage import MODELO_PADRAO  # noqa: E402


def _embedder_nao_deveria_ser_chamado(textos: list[str]) -> list[list[float]]:
    raise RuntimeError(
        "Cache do Perfil V4 incompleto/desatualizado — precisaria chamar a API "
        f"da Voyage para {len(textos)} unidade(s). Rode a etapa de embedding do "
        "perfil de novo antes deste comparativo."
    )


def carregar_editais_da_base_teste() -> list[dict]:
    editais: list[dict] = []
    for caminho in sorted(glob.glob("base-teste/editais-embeddados_2026-07-*.json")):
        dados = json.load(open(caminho, encoding="utf-8"))
        editais.extend(dados["editais"])
    return editais


def main() -> None:
    n_top = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    perfil = carregar_perfil(
        Path("perfil/produtos-aurora"), _embedder_nao_deveria_ser_chamado, MODELO_PADRAO
    )
    print(f"Perfil V4 carregado do cache: {len(perfil)} vetores.", flush=True)

    matriz_perfil = np.array([p.vetor for p in perfil], dtype=np.float32)
    matriz_perfil /= np.linalg.norm(matriz_perfil, axis=1, keepdims=True)
    nomes_perfil = [p.nome for p in perfil]

    editais = carregar_editais_da_base_teste()
    print(f"Editais carregados da base de teste: {len(editais)}.", flush=True)

    matriz_editais = np.array([e["embedding"] for e in editais], dtype=np.float32)
    matriz_editais /= np.linalg.norm(matriz_editais, axis=1, keepdims=True)

    # similaridade[i, j] = cosseno entre edital i e unidade de perfil j
    # (vetores já normalizados -> produto escalar == cosseno)
    similaridade = matriz_editais @ matriz_perfil.T
    melhor_indice = similaridade.argmax(axis=1)
    melhor_score = similaridade[np.arange(len(editais)), melhor_indice]

    resultados = [
        {
            "numeroControlePNCP": e["numeroControlePNCP"],
            "objetoCompra": e["objetoCompra"],
            "score_v4": float(melhor_score[i]),
            "produto_v4": nomes_perfil[melhor_indice[i]],
        }
        for i, e in enumerate(editais)
    ]
    resultados.sort(key=lambda r: r["score_v4"], reverse=True)
    top = resultados[:n_top]

    caminho_saida = Path("base-teste/comparacao-v1-v2-v3/top100_v4.json")
    caminho_saida.write_text(json.dumps(top, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTop {len(top)} salvo em {caminho_saida}", flush=True)

    print("\n=== TOP 15 por Score V4 ===", flush=True)
    for r in top[:15]:
        print(
            f"{r['score_v4']:.4f}  {r['produto_v4']:<34} | {r['objetoCompra'][:70]}",
            flush=True,
        )


if __name__ == "__main__":
    main()
