"""Reembedda o Perfil Aurora e o Perfil de Prioridade com o Gemini.

Pré-requisito para comparar os chunks (também a serem reembeddados com o
Gemini) contra esses perfis: embeddings só são comparáveis dentro do mesmo
modelo (base-teste/README.md, ADR-0001). O cache em `perfil/*/.embeddings/`
é hash de conteúdo + nome do modelo, então isso não sobrescreve o que já
existe para a Voyage — só adiciona entradas novas.
"""

from __future__ import annotations

from pathlib import Path

from editais.prioridade import carregar_perfil_prioridade
from editais.transporte_gemini import MODELO_PADRAO, criar_embedder_gemini
from editais.triagem import carregar_perfil

DIRETORIO_PERFIL = Path("perfil/produtos-aurora")
DIRETORIO_PERFIL_PRIORIDADE = Path("perfil/prioridade")


def main() -> None:
    embedder = criar_embedder_gemini()

    print("Perfil Aurora...", flush=True)
    perfil = carregar_perfil(DIRETORIO_PERFIL, embedder, MODELO_PADRAO)
    print(f"  {len(perfil)} unidades (Aplicações Típicas + termos)", flush=True)

    print("Perfil de Prioridade...", flush=True)
    perfil_prioridade = carregar_perfil_prioridade(
        DIRETORIO_PERFIL_PRIORIDADE, embedder, MODELO_PADRAO
    )
    print(f"  {len(perfil_prioridade)} unidades (baixa/incluir)", flush=True)

    print("\nOK — caches gravados em perfil/*/.embeddings/ sob o modelo "
          f"'{MODELO_PADRAO}'.", flush=True)


if __name__ == "__main__":
    main()
