"""Extrai o texto do(s) documento(s) principal(is) do top-N (padrão 20) de
uma Análise profunda já rodada, para leitura humana ou de um agente — não
julga aderência, só prepara o material.

Uso: extrair_textos_para_leitura.py --data 2026-08-05 [--top 20]

Saída: dados/leitura_{data}.txt
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from editais.documentos import ArquivoEdital, listar_arquivos, selecionar_documentos_principais
from editais.extracao import extrair_textos_de_arquivo
from editais.transporte_http import listar_arquivos_via_http

DADOS = Path("dados")
DIRETORIO_DOCUMENTOS = DADOS / "documentos"
CACHE_LISTAGENS = DADOS / ".listagens_pncp.json"
CHARS_POR_DOCUMENTO = 1800


def slug(numero: str) -> str:
    return numero.replace("/", "_").replace("\\", "_")


def carregar_top(data: str, top: int, pular: int = 0) -> list[str]:
    # Ranqueia todos os analisados por Score, em vez de filtrar por
    # selecionado_para_revisao: para pular > 0 o recorte cai fora da marcação
    # (que cobre só o topo). Com pular=0 o resultado é idêntico ao da marcação,
    # já que ela é exatamente o top-N por Score.
    caminho = DADOS / f"analise_profunda_{data}.json"
    analisados = json.loads(caminho.read_text(encoding="utf-8"))
    analisados.sort(key=lambda e: e["score_aderencia"], reverse=True)
    return [e["numeroControlePNCP"] for e in analisados[pular : pular + top]]


def indexar_editais(data: str) -> dict[str, dict]:
    caminho = DADOS / f"editais_{data}.json"
    return {e["numeroControlePNCP"]: e for e in json.loads(caminho.read_text(encoding="utf-8"))}


def arquivos_locais_por_sequencial(diretorio: Path) -> dict[int, Path]:
    encontrados: dict[int, Path] = {}
    if not diretorio.is_dir():
        return encontrados
    for caminho in diretorio.iterdir():
        if not caminho.is_file():
            continue
        prefixo, separador, _ = caminho.name.partition("_")
        if separador and prefixo.isdigit():
            encontrados[int(prefixo)] = caminho
    return encontrados


def obter_arquivos(
    numero: str, edital: dict, cache: dict[str, list[dict]]
) -> list[ArquivoEdital] | None:
    if numero in cache:
        return [
            ArquivoEdital(
                sequencial_documento=a["sequencial"],
                titulo=a["titulo"],
                tipo_documento_nome=a["tipo"],
                url="",
                data_publicacao_pncp="",
            )
            for a in cache[numero]
        ]
    resultado = listar_arquivos(
        edital["orgaoEntidade"]["cnpj"],
        edital["anoCompra"],
        edital["sequencialCompra"],
        listar_arquivos_via_http,
        dormir=time.sleep,
    )
    if resultado.erro is not None:
        return None
    cache[numero] = [
        {"sequencial": a.sequencial_documento, "tipo": a.tipo_documento_nome, "titulo": a.titulo}
        for a in resultado.arquivos
    ]
    CACHE_LISTAGENS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    time.sleep(1.0)
    return resultado.arquivos


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrai texto dos principais para leitura.")
    parser.add_argument("--data", required=True, help="Data de referência (AAAA-MM-DD).")
    parser.add_argument("--top", type=int, default=20, help="Quantos editais (padrão: 20).")
    parser.add_argument(
        "--pular",
        type=int,
        default=0,
        help="Pula os N primeiros do ranking (ex.: --pular 20 --top 20 pega do 21º ao 40º).",
    )
    args = parser.parse_args()

    numeros = carregar_top(args.data, args.top, args.pular)
    idx = indexar_editais(args.data)
    cache = json.loads(CACHE_LISTAGENS.read_text(encoding="utf-8")) if CACHE_LISTAGENS.exists() else {}

    # Sufixo com o deslocamento para não sobrescrever a leitura de outra faixa
    # do ranking (ex.: leitura_2026-08-11.txt vs leitura_2026-08-11_de21.txt).
    sufixo = "" if args.pular == 0 else f"_de{args.pular + 1}"
    saida = DADOS / f"leitura_{args.data}{sufixo}.txt"
    linhas: list[str] = []

    for posicao, numero in enumerate(numeros, start=1):
        linhas.append("=" * 90)
        linhas.append(numero)
        linhas.append("=" * 90)

        edital = idx.get(numero)
        if edital is None:
            linhas.append("  [sem metadados em editais_*.json]")
            print(f"[{posicao}/{len(numeros)}] {numero}: sem metadados", flush=True)
            continue

        arquivos = obter_arquivos(numero, edital, cache)
        if arquivos is None:
            linhas.append("  [FALHA ao listar documentos no PNCP]")
            print(f"[{posicao}/{len(numeros)}] {numero}: FALHA ao listar", flush=True)
            continue

        principais = selecionar_documentos_principais(arquivos)
        linhas.append(
            f"  documentos principais: "
            f"{[(a.sequencial_documento, a.tipo_documento_nome) for a in principais]}"
        )

        locais = arquivos_locais_por_sequencial(DIRETORIO_DOCUMENTOS / slug(numero))
        for arquivo in principais:
            caminho = locais.get(arquivo.sequencial_documento)
            if caminho is None:
                linhas.append(f"  [seq {arquivo.sequencial_documento} ausente em disco]")
                continue
            nome_original = caminho.name.partition("_")[2]
            extraidos = extrair_textos_de_arquivo(nome_original, caminho.read_bytes())
            texto = "\n".join(t.texto for t in extraidos)
            linhas.append(f"\n  --- {caminho.name} ({len(texto)} chars extraídos) ---")
            linhas.append("  " + texto[:CHARS_POR_DOCUMENTO].replace("\n", "\n  "))
        linhas.append("")
        print(f"[{posicao}/{len(numeros)}] {numero}: ok", flush=True)

    saida.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nsaída: {saida}", flush=True)


if __name__ == "__main__":
    main()
