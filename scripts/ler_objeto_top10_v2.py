"""Extrai o texto do(s) documento(s) principal(is) dos editais do top-10 (run
Voyage) para leitura humana do objeto real — não confia no Score, lê o
documento de fato, mesma lista de documentos principais usada na Análise
profunda (selecionar_documentos_principais + fallback hierárquico).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from editais.documentos import ArquivoEdital, listar_arquivos, selecionar_documentos_principais
from editais.extracao import extrair_textos_de_arquivo
from editais.transporte_http import listar_arquivos_via_http

DADOS = Path("dados")
DIRETORIO_DOCUMENTOS = DADOS / "documentos"
CACHE_LISTAGENS = DADOS / ".listagens_pncp.json"


def indexar_editais() -> dict[str, dict]:
    indice: dict[str, dict] = {}
    for caminho in DADOS.glob("editais_*.json"):
        for edital in json.loads(caminho.read_text(encoding="utf-8")):
            indice[edital["numeroControlePNCP"]] = edital
    return indice

TOP_10 = [
    "03929049000111-1-000025/2026",
    "82892373000189-1-000028/2026",
    "08079915000146-1-000043/2026",
    "13718176000125-1-000019/2026",
    "27080605000609-1-000042/2026",
    "50453703000143-1-000052/2026",
    "50453703000143-1-000051/2026",
    "92963560000160-1-001335/2025",
    "08996378000107-1-000089/2026",
    "60448040000122-1-000511/2026",
]


def slug(numero: str) -> str:
    return numero.replace("/", "_").replace("\\", "_")


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


def main() -> None:
    cache = json.loads(CACHE_LISTAGENS.read_text(encoding="utf-8")) if CACHE_LISTAGENS.exists() else {}
    indice = indexar_editais()
    saida = Path("dados/leitura_top10.txt")
    linhas: list[str] = []

    for numero in TOP_10:
        linhas.append("=" * 90)
        linhas.append(numero)
        linhas.append("=" * 90)

        listagem = cache.get(numero)
        if listagem is None:
            edital = indice.get(numero)
            if edital is None:
                linhas.append("  [sem metadados em dados/editais_*.json]")
                continue
            resultado = listar_arquivos(
                edital["orgaoEntidade"]["cnpj"],
                edital["anoCompra"],
                edital["sequencialCompra"],
                listar_arquivos_via_http,
                dormir=time.sleep,
            )
            if resultado.erro is not None:
                linhas.append(f"  [FALHA ao listar: {resultado.erro}]")
                continue
            listagem = [
                {
                    "sequencial": a.sequencial_documento,
                    "tipo": a.tipo_documento_nome,
                    "titulo": a.titulo,
                }
                for a in resultado.arquivos
            ]
            cache[numero] = listagem
            CACHE_LISTAGENS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            time.sleep(1.0)

        arquivos = [
            ArquivoEdital(
                sequencial_documento=a["sequencial"],
                titulo=a["titulo"],
                tipo_documento_nome=a["tipo"],
                url="",
                data_publicacao_pncp="",
            )
            for a in listagem
        ]
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
            linhas.append("  " + texto[:1800].replace("\n", "\n  "))
        linhas.append("")
        print(f"[ok] {numero}", flush=True)

    saida.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nsaída: {saida}", flush=True)


if __name__ == "__main__":
    main()
