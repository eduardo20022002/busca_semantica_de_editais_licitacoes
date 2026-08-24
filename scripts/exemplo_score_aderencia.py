"""Exemplo didático, com dados reais e vetores já cacheados (sem chamar a API
de novo): mostra passo a passo como o Score de aderência de um edital é
calculado, usando alguns Chunks reais e o Perfil Aurora real.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from editais.prioridade import (
    GRUPO_BAIXA,
    carregar_perfil_prioridade,
    classificar_chunk,
    extrair_unidades_de_prioridade,
)
from editais.triagem import extrair_unidades_de_texto, similaridade_cosseno

MODELO = "voyage-4"
NUMERO = "08351513000159-1-000071/2026"

# Chunks escolhidos a dedo do próprio edital, para o exemplo ficar legível.
INDICE_RELEVANTE = 73  # funcionalidades de prontuário eletrônico
INDICE_BOILERPLATE = 33  # habilitação jurídica


def carregar_cache_chunks() -> dict[str, list[float]]:
    dados = json.loads(Path("dados/.embeddings/chunks.json").read_text(encoding="utf-8"))
    assert dados["modelo"] == MODELO, f"cache está em {dados['modelo']}, não {MODELO}"
    return dados["vetores"]


def vetor_do_chunk(texto: str, cache: dict[str, list[float]]) -> list[float]:
    h = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    return cache[h]


def carregar_unidades_do_perfil(caminho_md: Path) -> list[tuple[str, list[float]]]:
    conteudo = caminho_md.read_text(encoding="utf-8")
    textos = extrair_unidades_de_texto(conteudo)
    caminho_cache = caminho_md.parent / ".embeddings" / f"{caminho_md.stem}.json"
    dados = json.loads(caminho_cache.read_text(encoding="utf-8"))
    assert dados["modelo"] == MODELO
    unidades = dados["unidades"]
    assert len(unidades) == len(textos)
    return [(u["texto"], u["vetor"]) for u in unidades]


def main() -> None:
    cache_chunks = carregar_cache_chunks()
    chunks = json.loads(
        Path(f"dados/chunks/{NUMERO.replace('/', '_')}.json").read_text(encoding="utf-8")
    )["chunks"]

    chunk_relevante = chunks[INDICE_RELEVANTE]
    chunk_boilerplate = chunks[INDICE_BOILERPLATE]

    print(f"Edital: {NUMERO}  ({len(chunks)} chunks no total)\n")
    print(f"[Chunk {INDICE_RELEVANTE}] (relevante, sobre PEC):")
    print(f"  {chunk_relevante[:200]!r}\n")
    print(f"[Chunk {INDICE_BOILERPLATE}] (boilerplate, habilitação jurídica):")
    print(f"  {chunk_boilerplate[:200]!r}\n")

    vetor_relevante = vetor_do_chunk(chunk_relevante, cache_chunks)
    vetor_boilerplate = vetor_do_chunk(chunk_boilerplate, cache_chunks)

    # --- Passo 1: Prioridade de seção (BAIXA x INCLUIR) ---
    perfil_prioridade = carregar_perfil_prioridade(
        Path("perfil/prioridade"),
        embedder=lambda textos: [],  # não deve ser chamado: tudo já está em cache
        modelo=MODELO,
    )
    print("=" * 80)
    print("PASSO 1 — Prioridade de seção (filtra ANTES do pooling)")
    print("=" * 80)
    for rotulo, vetor in [("relevante", vetor_relevante), ("boilerplate", vetor_boilerplate)]:
        classe = classificar_chunk(vetor, perfil_prioridade)
        marca = "EXCLUÍDO do pooling" if classe == GRUPO_BAIXA else "entra no pooling"
        print(f"  chunk '{rotulo}' -> classificado como {classe.upper()} ({marca})")

    # --- Passo 2: Perfil Aurora — Aplicações Típicas de um produto ---
    caminho_md = Path("perfil/produtos-aurora/software-de-gestao-em-saude.md")
    unidades = carregar_unidades_do_perfil(caminho_md)

    print("\n" + "=" * 80)
    print("PASSO 2 — Aplicações Típicas do produto 'software-de-gestao-em-saude'")
    print("=" * 80)
    for i, (texto, _) in enumerate(unidades):
        print(f"  [{i}] {texto[:90]}")

    # --- Passo 3: cosseno de cada Chunk contra cada sub-vetor do produto ---
    print("\n" + "=" * 80)
    print("PASSO 3 — Similaridade de cosseno: chunk x cada Aplicação Típica")
    print("=" * 80)
    for rotulo, vetor_chunk in [
        ("RELEVANTE (prontuário eletrônico)", vetor_relevante),
        ("BOILERPLATE (habilitação jurídica)", vetor_boilerplate),
    ]:
        print(f"\n  chunk {rotulo}:")
        melhor = ("", -1.0)
        for texto, vetor_unidade in unidades:
            score = similaridade_cosseno(vetor_chunk, vetor_unidade)
            print(f"    {score:.4f}  vs  {texto[:70]}")
            if score > melhor[1]:
                melhor = (texto, score)
        print(f"    -> MÁXIMO deste chunk: {melhor[1]:.4f} (\"{melhor[0][:60]}\")")

    print("\n" + "=" * 80)
    print("CONCLUSÃO")
    print("=" * 80)
    print(
        "O Score de aderência do edital é o MAIOR valor entre TODOS os chunks que\n"
        "passaram pela Prioridade de seção (não só estes dois) contra TODOS os\n"
        "sub-vetores de TODOS os produtos Aurora (não só este produto). O chunk\n"
        "boilerplate nem participa dessa conta — foi excluído no Passo 1."
    )


if __name__ == "__main__":
    main()
