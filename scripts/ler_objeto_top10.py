"""Extrai o texto do(s) documento(s) principal(is) dos editais do top-10 (run
Voyage) para leitura humana do objeto real — não confia no Score, lê o
documento de fato, mesma lista de documentos principais usada na Análise
profunda (selecionar_documentos_principais + fallback hierárquico).
"""

from __future__ import annotations

import json
from pathlib import Path

from editais.documentos import ArquivoEdital, selecionar_documentos_principais
from editais.extracao import extrair_textos_de_arquivo

DADOS = Path("dados")
DIRETORIO_DOCUMENTOS = DADOS / "documentos"
CACHE_LISTAGENS = DADOS / ".listagens_pncp.json"

TOP_10 = [
    "75789552000120-1-000047/2026",
    "11204871000143-1-000004/2026",
    "18457192000125-1-000021/2026",
    "08351513000159-1-000071/2026",
    "46374500000194-1-005442/2026",
    "01146604000103-1-000097/2026",
    "47498340000158-1-000001/2026",
    "76995463000100-1-000056/2026",
    "95422986000102-1-000153/2026",
    "15126437000305-1-002477/2026",
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
    cache = json.loads(CACHE_LISTAGENS.read_text(encoding="utf-8"))
    saida = Path("dados/leitura_top10.txt")
    linhas: list[str] = []

    for numero in TOP_10:
        linhas.append("=" * 90)
        linhas.append(numero)
        linhas.append("=" * 90)

        listagem = cache.get(numero)
        if listagem is None:
            linhas.append("  [sem listagem em cache]")
            continue

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
