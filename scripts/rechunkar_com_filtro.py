"""Regera dados/chunks/ com o código atual, aplicando o filtro Edital/TR.

Os chunks em disco foram gerados em 20/07, um dia antes do filtro de documentos
principais (issue #7, commit 80a9d75) entrar no código — e a idempotência por
`dataAtualizacaoGlobal` não invalida cache por mudança de código, então eles
seguem contendo texto de anexos que o pipeline atual descartaria.

Este script refaz o chunking a partir dos arquivos JÁ baixados em
dados/documentos/ (sem novo download): só a listagem de metadados do PNCP é
consultada, para saber o `tipoDocumentoNome` de cada sequencial — essa
informação não está no nome do arquivo local.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from editais.chunking import chunkar_texto
from editais.documentos import ArquivoEdital, selecionar_documentos_principais
from editais.extracao import extrair_textos_de_arquivo
from editais.transporte_http import listar_arquivos_via_http
from editais.documentos import listar_arquivos

DADOS = Path("dados")
DIRETORIO_CHUNKS = DADOS / "chunks"
DIRETORIO_DOCUMENTOS = DADOS / "documentos"
# Preenchido por scripts/diagnosticar_documentos.py — reusar o cache evita
# depender de novo da API do PNCP, que vinha instável (504/429).
CACHE_LISTAGENS = DADOS / ".listagens_pncp.json"

# Espaçamento entre listagens do PNCP: a API de consulta vinha instável
# (504/429), então vale ser conservador — são só 100 chamadas de metadados.
SEGUNDOS_ENTRE_LISTAGENS = 1.0


def slug(texto: str) -> str:
    return texto.replace("/", "_").replace("\\", "_")


def indexar_editais() -> dict[str, dict]:
    indice: dict[str, dict] = {}
    for caminho in DADOS.glob("editais_*.json"):
        for edital in json.loads(caminho.read_text(encoding="utf-8")):
            indice[edital["numeroControlePNCP"]] = edital
    return indice


def arquivos_locais_por_sequencial(diretorio: Path) -> dict[int, Path]:
    """Mapeia sequencial -> caminho local, a partir do prefixo '{seq}_' do nome."""
    por_sequencial: dict[int, Path] = {}
    for caminho in diretorio.iterdir():
        if not caminho.is_file():
            continue
        prefixo, separador, _ = caminho.name.partition("_")
        if separador and prefixo.isdigit():
            por_sequencial[int(prefixo)] = caminho
    return por_sequencial


def carregar_cache_listagens() -> dict[str, list[dict]]:
    if CACHE_LISTAGENS.exists():
        return json.loads(CACHE_LISTAGENS.read_text(encoding="utf-8"))
    return {}


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
    time.sleep(SEGUNDOS_ENTRE_LISTAGENS)
    return None if resultado.erro is not None else resultado.arquivos


def main() -> None:
    indice = indexar_editais()
    cache = carregar_cache_listagens()
    caminhos_chunks = sorted(DIRETORIO_CHUNKS.glob("*.json"))
    print(
        f"Rechunkando {len(caminhos_chunks)} editais "
        f"({len(cache)} listagens em cache).\n",
        flush=True,
    )

    relatorio: list[dict] = []
    for posicao, caminho_chunks in enumerate(caminhos_chunks, start=1):
        nome_slug = caminho_chunks.stem
        numero = nome_slug.replace("_", "/")
        edital = indice.get(numero)
        antes = len(json.loads(caminho_chunks.read_text(encoding="utf-8")).get("chunks", []))

        if edital is None:
            print(f"[{posicao}/{len(caminhos_chunks)}] {numero}: sem metadados, pulado", flush=True)
            continue

        arquivos = obter_arquivos(numero, edital, cache)
        if arquivos is None:
            print(
                f"[{posicao}/{len(caminhos_chunks)}] {numero}: FALHA ao listar — mantido como está",
                flush=True,
            )
            continue

        principais = selecionar_documentos_principais(arquivos)
        sequenciais = {a.sequencial_documento for a in principais}
        locais = arquivos_locais_por_sequencial(DIRETORIO_DOCUMENTOS / nome_slug)

        textos: list[str] = []
        usados = 0
        ausentes = 0
        for sequencial in sorted(sequenciais):
            caminho_arquivo = locais.get(sequencial)
            if caminho_arquivo is None:
                ausentes += 1
                continue
            # O nome usado na extração precisa ter a extensão real: o despacho
            # por tipo de arquivo (pdf/docx/xlsx/zip) é feito por extensão.
            nome_original = caminho_arquivo.name.partition("_")[2]
            extraidos = extrair_textos_de_arquivo(nome_original, caminho_arquivo.read_bytes())
            textos.extend(t.texto for t in extraidos)
            usados += 1

        chunks = chunkar_texto("\n".join(textos))
        caminho_chunks.write_text(
            json.dumps(
                {
                    "dataAtualizacaoGlobal": edital.get("dataAtualizacaoGlobal", ""),
                    "chunks": chunks,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        relatorio.append(
            {
                "numero": numero,
                "docs_total": len(arquivos),
                "docs_principais": len(sequenciais),
                "docs_usados": usados,
                "docs_ausentes": ausentes,
                "chunks_antes": antes,
                "chunks_depois": len(chunks),
            }
        )
        aviso = ""
        if not sequenciais:
            aviso = "  [SEM Edital/TR]"
        elif ausentes:
            aviso = f"  [{ausentes} arquivo(s) principal(is) ausente(s) em disco]"
        print(
            f"[{posicao}/{len(caminhos_chunks)}] {numero}: "
            f"{len(arquivos)} docs -> {usados} principais | "
            f"chunks {antes} -> {len(chunks)}{aviso}",
            flush=True,
        )

    (DADOS / "relatorio_rechunk.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_antes = sum(r["chunks_antes"] for r in relatorio)
    total_depois = sum(r["chunks_depois"] for r in relatorio)
    sem_principal = [r for r in relatorio if r["docs_principais"] == 0]
    vazios = [r for r in relatorio if r["chunks_depois"] == 0]

    print("\n" + "=" * 60, flush=True)
    print(f"editais rechunkados: {len(relatorio)}", flush=True)
    print(f"chunks antes:  {total_antes}", flush=True)
    print(f"chunks depois: {total_depois}", flush=True)
    print(f"editais sem Edital/TR na listagem: {len(sem_principal)}", flush=True)
    print(f"editais que ficaram com 0 chunks:  {len(vazios)}", flush=True)
    print("relatorio por edital: dados/relatorio_rechunk.json", flush=True)


if __name__ == "__main__":
    main()
