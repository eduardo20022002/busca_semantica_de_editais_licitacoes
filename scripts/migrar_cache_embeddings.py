"""Converte os caches de embeddings do formato antigo (um único objeto JSON
reescrito por inteiro a cada persistência) para o novo append-only (uma linha
JSON por vetor).

Motivo: com o cache de Chunks em 1,19 GB, cada edital custava ~100s, quase
todo ele gasto reescrevendo o arquivo inteiro para gravar ~2,7 MB de vetores
novos. Ver o comentário em editais.triagem._anexar_ao_cache.

Uso: python scripts/migrar_cache_embeddings.py [--apagar-antigos]

Não apaga o arquivo antigo por padrão — confira o resultado antes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DIRETORIO = Path("dados/.embeddings")

# (arquivo antigo, arquivo novo, modelo com que foi gerado)
MIGRACOES = [
    ("chunks.json", "chunks.jsonl"),
    ("objetos_compra.json", "objetos_compra.jsonl"),
]


def migrar(nome_antigo: str, nome_novo: str) -> None:
    origem = DIRETORIO / nome_antigo
    destino = DIRETORIO / nome_novo

    if not origem.exists():
        print(f"  {nome_antigo}: não existe, pulado")
        return
    if destino.exists():
        print(f"  {nome_novo}: já existe, pulado (apague antes se quiser refazer)")
        return

    print(f"  lendo {nome_antigo} ({origem.stat().st_size / 1e9:.2f} GB)...", flush=True)
    dados = json.loads(origem.read_text(encoding="utf-8"))
    modelo = dados.get("modelo", "")
    vetores: dict[str, list[float]] = dados.get("vetores", {})

    print(f"  gravando {len(vetores)} vetores (modelo={modelo}) em {nome_novo}...", flush=True)
    temporario = destino.with_suffix(destino.suffix + ".parcial")
    with temporario.open("w", encoding="utf-8") as arquivo:
        for hash_texto, vetor in vetores.items():
            arquivo.write(
                json.dumps({"modelo": modelo, "hash": hash_texto, "vetor": vetor}) + "\n"
            )
    # Só assume o nome final quando a escrita terminou por completo — um
    # processo morto no meio deixa um .parcial, não um cache truncado que
    # pareceria válido.
    temporario.replace(destino)
    print(f"  ok: {nome_novo} ({destino.stat().st_size / 1e9:.2f} GB)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra caches de embeddings para append-only.")
    parser.add_argument(
        "--apagar-antigos",
        action="store_true",
        help="apaga os .json antigos após migrar (padrão: mantém).",
    )
    args = parser.parse_args()

    for nome_antigo, nome_novo in MIGRACOES:
        print(f"{nome_antigo} -> {nome_novo}")
        migrar(nome_antigo, nome_novo)
        if args.apagar_antigos:
            origem = DIRETORIO / nome_antigo
            if origem.exists() and (DIRETORIO / nome_novo).exists():
                origem.unlink()
                print(f"  apagado {nome_antigo}")

    print("migração concluída")


if __name__ == "__main__":
    main()
