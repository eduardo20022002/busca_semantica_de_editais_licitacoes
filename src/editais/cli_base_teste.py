from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from editais.base_teste import montar_base
from editais.transporte_voyage import MODELO_PADRAO, criar_embedder_voyage
from editais.triagem import criar_embedder_com_cache

DIRETORIO_DADOS = Path("dados")
DIRETORIO_BASE = Path("base-teste")
CACHE_OBJETOS_COMPRA = DIRETORIO_DADOS / ".embeddings" / "objetos_compra.jsonl"
INPUT_TYPE = "document"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Gera a Base de teste: editais com seus objetos embeddados."
    )
    parser.add_argument(
        "--data",
        help="Data específica AAAA-MM-DD. Se omitido, processa todos os dias em dados/.",
        default=None,
    )
    args = parser.parse_args(argv)

    if args.data:
        entradas = [DIRETORIO_DADOS / f"editais_{args.data}.json"]
    else:
        entradas = sorted(DIRETORIO_DADOS.glob("editais_*.json"))

    if not entradas:
        print("Nenhum arquivo de editais encontrado em dados/.")
        return

    embedder = criar_embedder_voyage()
    embedder_cacheado = criar_embedder_com_cache(embedder, CACHE_OBJETOS_COMPRA, MODELO_PADRAO)
    DIRETORIO_BASE.mkdir(parents=True, exist_ok=True)

    for entrada in entradas:
        data_referencia = entrada.stem.replace("editais_", "")
        editais = json.loads(entrada.read_text(encoding="utf-8"))
        base = montar_base(editais, embedder_cacheado)

        conteudo = {
            "metadados": {
                "titulo": "Base de teste - Editais com seus objetos embeddados",
                "modelo": MODELO_PADRAO,
                "input_type": INPUT_TYPE,
                "dimensao": len(base[0]["embedding"]) if base else 0,
                "data_referencia": data_referencia,
                "quantidade": len(base),
                "gerado_em": datetime.now(timezone.utc).isoformat(),
            },
            "editais": base,
        }

        saida = DIRETORIO_BASE / f"editais-embeddados_{data_referencia}.json"
        saida.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
        print(f"Base de {data_referencia}: {len(base)} editais embeddados em {saida}")


if __name__ == "__main__":
    main()
