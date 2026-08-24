"""Diagnostica por que editais ficam sem texto na Análise profunda.

Cruza três fontes por edital: a listagem de documentos do PNCP (tipo de cada
arquivo), o que existe de fato em dados/documentos/, e o resultado real da
extração de texto de cada arquivo.

Cacheia as listagens em dados/.listagens_pncp.json para permitir reexecutar o
diagnóstico offline (a API do PNCP vinha instável).
"""

from __future__ import annotations

import collections
import json
import time
from pathlib import Path

from editais.documentos import listar_arquivos
from editais.extracao import extrair_textos_de_arquivo
from editais.transporte_http import listar_arquivos_via_http

DADOS = Path("dados")
DIRETORIO_CHUNKS = DADOS / "chunks"
DIRETORIO_DOCUMENTOS = DADOS / "documentos"
CACHE_LISTAGENS = DADOS / ".listagens_pncp.json"

SEGUNDOS_ENTRE_LISTAGENS = 1.0


def slug(texto: str) -> str:
    return texto.replace("/", "_").replace("\\", "_")


def indexar_editais() -> dict[str, dict]:
    indice: dict[str, dict] = {}
    for caminho in DADOS.glob("editais_*.json"):
        for edital in json.loads(caminho.read_text(encoding="utf-8")):
            indice[edital["numeroControlePNCP"]] = edital
    return indice


def carregar_cache() -> dict[str, list[dict]]:
    if CACHE_LISTAGENS.exists():
        return json.loads(CACHE_LISTAGENS.read_text(encoding="utf-8"))
    return {}


def obter_listagem(numero: str, edital: dict, cache: dict[str, list[dict]]) -> list[dict] | None:
    if numero in cache:
        return cache[numero]
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
        {
            "sequencial": a.sequencial_documento,
            "tipo": a.tipo_documento_nome,
            "titulo": a.titulo,
        }
        for a in resultado.arquivos
    ]
    CACHE_LISTAGENS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    time.sleep(SEGUNDOS_ENTRE_LISTAGENS)
    return cache[numero]


def arquivos_locais(diretorio: Path) -> dict[int, Path]:
    if not diretorio.is_dir():
        return {}
    encontrados: dict[int, Path] = {}
    for caminho in diretorio.iterdir():
        if not caminho.is_file():
            continue
        prefixo, separador, _ = caminho.name.partition("_")
        if separador and prefixo.isdigit():
            encontrados[int(prefixo)] = caminho
    return encontrados


def main() -> None:
    indice = indexar_editais()
    cache = carregar_cache()
    print(f"listagens em cache: {len(cache)}\n", flush=True)

    tipos_globais: collections.Counter[str] = collections.Counter()
    extensoes_globais: collections.Counter[str] = collections.Counter()
    # Extensões que produziram zero texto (formato não suportado ou arquivo quebrado).
    falhas_por_extensao: collections.Counter[str] = collections.Counter()
    relatorio: list[dict] = []

    caminhos = sorted(DIRETORIO_CHUNKS.glob("*.json"))
    for posicao, caminho_chunks in enumerate(caminhos, start=1):
        nome_slug = caminho_chunks.stem
        numero = nome_slug.replace("_", "/")
        edital = indice.get(numero)
        if edital is None:
            continue

        listagem = obter_listagem(numero, edital, cache)
        if listagem is None:
            print(f"[{posicao}/{len(caminhos)}] {numero}: FALHA ao listar", flush=True)
            continue

        locais = arquivos_locais(DIRETORIO_DOCUMENTOS / nome_slug)
        detalhes = []
        for arquivo in listagem:
            tipos_globais[arquivo["tipo"]] += 1
            caminho_local = locais.get(arquivo["sequencial"])
            registro = {
                "sequencial": arquivo["sequencial"],
                "tipo": arquivo["tipo"],
                "titulo": arquivo["titulo"],
                "em_disco": caminho_local is not None,
                "extensao": caminho_local.suffix.lower() if caminho_local else None,
                "chars_extraidos": 0,
            }
            if caminho_local is not None:
                extensoes_globais[caminho_local.suffix.lower()] += 1
                nome_original = caminho_local.name.partition("_")[2]
                extraidos = extrair_textos_de_arquivo(
                    nome_original, caminho_local.read_bytes()
                )
                registro["chars_extraidos"] = sum(len(t.texto) for t in extraidos)
                if registro["chars_extraidos"] == 0:
                    falhas_por_extensao[caminho_local.suffix.lower()] += 1
            detalhes.append(registro)

        chunks_atuais = len(
            json.loads(caminho_chunks.read_text(encoding="utf-8")).get("chunks", [])
        )
        relatorio.append(
            {"numero": numero, "chunks_atuais": chunks_atuais, "documentos": detalhes}
        )
        print(f"[{posicao}/{len(caminhos)}] {numero}: {len(detalhes)} docs", flush=True)

    (DADOS / "diagnostico_documentos.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 70, flush=True)
    print("TIPOS DE DOCUMENTO (todos os editais)", flush=True)
    for tipo, quantidade in tipos_globais.most_common():
        print(f"  {quantidade:5d}  {tipo}", flush=True)

    print("\nEXTENSOES EM DISCO", flush=True)
    for extensao, quantidade in extensoes_globais.most_common():
        falhas = falhas_por_extensao.get(extensao, 0)
        print(f"  {quantidade:5d}  {extensao}   (sem texto: {falhas})", flush=True)

    print("\nEDITAIS COM ZERO CHUNKS HOJE", flush=True)
    for item in relatorio:
        if item["chunks_atuais"] > 0:
            continue
        print(f"\n  {item['numero']}", flush=True)
        for documento in item["documentos"]:
            estado = "em disco" if documento["em_disco"] else "AUSENTE"
            print(
                f"    seq={documento['sequencial']:<3} "
                f"tipo={documento['tipo']:<28} "
                f"ext={str(documento['extensao']):<7} "
                f"{estado:<9} chars={documento['chars_extraidos']}",
                flush=True,
            )

    print("\nrelatorio completo: dados/diagnostico_documentos.json", flush=True)


if __name__ == "__main__":
    main()
