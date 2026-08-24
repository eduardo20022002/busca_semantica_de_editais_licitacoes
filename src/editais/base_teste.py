from __future__ import annotations

from typing import Any

from editais.triagem import Embedder


def montar_base(editais: list[dict[str, Any]], embedder: Embedder) -> list[dict[str, Any]]:
    objetos = [edital["objetoCompra"] for edital in editais]
    vetores = embedder(objetos)
    return [
        {
            "numeroControlePNCP": edital["numeroControlePNCP"],
            "objetoCompra": edital["objetoCompra"],
            "embedding": vetor,
        }
        for edital, vetor in zip(editais, vetores)
    ]
