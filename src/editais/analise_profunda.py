from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editais.prioridade import GRUPO_BAIXA, GrupoPrioridade, classificar_chunk
from editais.triagem import Embedder, Produto, similaridade_cosseno


@dataclass(frozen=True)
class ScoreAderencia:
    numero_controle_pncp: str
    score_aderencia: float
    produto_mais_proximo: str


@dataclass(frozen=True)
class EditalAnalisado:
    numero_controle_pncp: str
    score_aderencia: float
    produto_mais_proximo: str
    selecionado_para_revisao: bool


def calcular_scores_aderencia(
    chunks_por_edital: dict[str, list[str]],
    embedder: Embedder,
    perfil: list[Produto],
    perfil_prioridade: list[GrupoPrioridade],
) -> list[ScoreAderencia]:
    # Embedda um edital por vez (não tudo num lote global): isola a falha de um
    # edital dos demais e deixa o cache de embeddings ser persistido a cada
    # edital, não só no fim de uma execução longa e limitada por rate limit.
    scores: list[ScoreAderencia] = []
    for numero, chunks in chunks_por_edital.items():
        try:
            vetores_do_edital = embedder(chunks) if chunks else []
        except RuntimeError:
            # Falha persistente de embedding (ex. rate limit esgotado após todas
            # as tentativas) não pode derrubar o restante da execução — pula
            # este edital, mantendo a promessa já documentada acima.
            continue
        # Prioridade de seção V1 (ADR-0005): exclui do max pooling os Chunks
        # classificados BAIXA (boilerplate jurídico/administrativo) — reaproveita
        # o vetor já calculado, sem embedding adicional.
        vetores_incluidos = [
            vetor
            for vetor in vetores_do_edital
            if classificar_chunk(vetor, perfil_prioridade) != GRUPO_BAIXA
        ]
        scores.append(_pontuar_edital(numero, vetores_incluidos, perfil))
    return scores


def _pontuar_edital(
    numero: str,
    vetores_do_edital: list[list[float]],
    perfil: list[Produto],
) -> ScoreAderencia:
    melhor_score = 0.0
    melhor_produto = ""
    for vetor in vetores_do_edital:
        for produto in perfil:
            score = similaridade_cosseno(vetor, produto.vetor)
            if score > melhor_score:
                melhor_score = score
                melhor_produto = produto.nome
    return ScoreAderencia(
        numero_controle_pncp=numero,
        score_aderencia=melhor_score,
        produto_mais_proximo=melhor_produto,
    )


def precisa_reprocessar(
    data_atualizacao_atual: str, data_atualizacao_processada: str | None
) -> bool:
    return data_atualizacao_processada != data_atualizacao_atual


def marcar_selecionados_para_revisao(
    scores: list[ScoreAderencia], n: int
) -> list[EditalAnalisado]:
    # Top-N absoluto, mesmo padrão de marcar_selecionados (triagem.py): evita
    # depender de um corte por valor de similaridade ainda não calibrado.
    ordenados = sorted(scores, key=lambda s: s.score_aderencia, reverse=True)
    return [
        EditalAnalisado(
            numero_controle_pncp=score.numero_controle_pncp,
            score_aderencia=score.score_aderencia,
            produto_mais_proximo=score.produto_mais_proximo,
            selecionado_para_revisao=posicao < n,
        )
        for posicao, score in enumerate(ordenados)
    ]


def serializar_analise_profunda(editais: list[EditalAnalisado]) -> list[dict[str, Any]]:
    return [
        {
            "numeroControlePNCP": e.numero_controle_pncp,
            "score_aderencia": e.score_aderencia,
            "produto_mais_proximo": e.produto_mais_proximo,
            "selecionado_para_revisao": e.selecionado_para_revisao,
        }
        for e in editais
    ]
