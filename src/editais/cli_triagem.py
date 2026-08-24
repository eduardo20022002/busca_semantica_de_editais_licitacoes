from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from editais.transporte_voyage import MODELO_PADRAO, criar_embedder_voyage
from editais.triagem import (
    calcular_scores_triagem,
    carregar_perfil,
    criar_embedder_com_cache,
    marcar_selecionados,
    serializar_triagem,
)

DIRETORIO_DADOS = Path("dados")
DIRETORIO_PERFIL = Path("perfil/produtos-aurora")
CACHE_OBJETOS_COMPRA = DIRETORIO_DADOS / ".embeddings" / "objetos_compra.jsonl"
TOP_N = 300


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Score de triagem dos editais coletados (Etapa 1)."
    )
    parser.add_argument(
        "--data",
        help="Data de referência no formato AAAA-MM-DD (padrão: ontem).",
        default=None,
    )
    args = parser.parse_args(argv)

    data_referencia = args.data or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    entrada = DIRETORIO_DADOS / f"editais_{data_referencia}.json"
    editais = json.loads(entrada.read_text(encoding="utf-8"))

    embedder = criar_embedder_voyage()
    perfil = carregar_perfil(DIRETORIO_PERFIL, embedder, MODELO_PADRAO)
    embedder_de_editais = criar_embedder_com_cache(embedder, CACHE_OBJETOS_COMPRA, MODELO_PADRAO)
    scores = calcular_scores_triagem(editais, embedder_de_editais, perfil)
    triados = marcar_selecionados(scores, n=TOP_N)

    saida = DIRETORIO_DADOS / f"triagem_{data_referencia}.json"
    saida.write_text(
        json.dumps(serializar_triagem(triados), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    selecionados = sum(1 for t in triados if t.selecionado_para_analise_profunda)
    print(
        f"Triados {len(triados)} editais; {selecionados} selecionados "
        f"para análise profunda em {saida}"
    )


if __name__ == "__main__":
    main()
