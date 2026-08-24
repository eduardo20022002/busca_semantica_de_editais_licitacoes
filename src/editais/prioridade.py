from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from editais.triagem import Embedder, carregar_unidades_com_cache, similaridade_cosseno

GRUPO_BAIXA = "baixa"
GRUPO_INCLUIR = "incluir"


@dataclass(frozen=True)
class GrupoPrioridade:
    nome: str
    vetor: list[float]


def extrair_unidades_de_prioridade(conteudo_markdown: str) -> list[str]:
    return [
        linha.strip()[2:].strip()
        for linha in conteudo_markdown.splitlines()
        if linha.strip().startswith("- ")
    ]


def carregar_perfil_prioridade(
    diretorio: Path, embedder: Embedder, modelo: str
) -> list[GrupoPrioridade]:
    pares = carregar_unidades_com_cache(
        diretorio, embedder, modelo, extrair_unidades_de_prioridade
    )
    return [GrupoPrioridade(nome=nome, vetor=vetor) for nome, vetor in pares]


def classificar_chunk(vetor: list[float], perfil_prioridade: list[GrupoPrioridade]) -> str:
    # Default seguro: BAIXA só vence se estritamente maior. Empate, ambiguidade,
    # ou Perfil de Prioridade vazio caem em INCLUIR (ADR-0005) — melhor incluir
    # Chunk demais do que descartar conteúdo potencialmente relevante.
    melhor_baixa = _melhor_similaridade(vetor, perfil_prioridade, GRUPO_BAIXA)
    melhor_incluir = _melhor_similaridade(vetor, perfil_prioridade, GRUPO_INCLUIR)
    return GRUPO_BAIXA if melhor_baixa > melhor_incluir else GRUPO_INCLUIR


def _melhor_similaridade(
    vetor: list[float], perfil_prioridade: list[GrupoPrioridade], grupo: str
) -> float:
    similaridades = [
        similaridade_cosseno(vetor, g.vetor) for g in perfil_prioridade if g.nome == grupo
    ]
    return max(similaridades, default=-1.0)
