from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from editais.coleta import coletar_editais
from editais.transporte_http import buscar_via_http

MODALIDADES = [4, 6]
DIRETORIO_SAIDA = Path("dados")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Coleta diária de editais publicados no PNCP (Etapa 0)."
    )
    parser.add_argument(
        "--data",
        help="Data de referência no formato AAAA-MM-DD (padrão: ontem).",
        default=None,
    )
    args = parser.parse_args(argv)

    data_referencia = args.data or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data_pncp = data_referencia.replace("-", "")

    resultado = coletar_editais(
        data_inicial=data_pncp,
        data_final=data_pncp,
        modalidades=MODALIDADES,
        buscar=buscar_via_http,
        dormir=time.sleep,
    )

    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
    caminho_saida = DIRETORIO_SAIDA / f"editais_{data_referencia}.json"
    caminho_saida.write_text(
        json.dumps(resultado.editais, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Coletados {len(resultado.editais)} editais em {caminho_saida}")
    if resultado.erros:
        print(f"{len(resultado.erros)} página(s) falharam após retries:")
        for erro in resultado.erros:
            print(f"  - modalidade={erro.modalidade} pagina={erro.pagina}: {erro.motivo}")


if __name__ == "__main__":
    main()
