import pytest

from editais.analise_profunda import (
    EditalAnalisado,
    ScoreAderencia,
    calcular_scores_aderencia,
    marcar_selecionados_para_revisao,
    precisa_reprocessar,
    serializar_analise_profunda,
)
from editais.prioridade import GRUPO_BAIXA, GRUPO_INCLUIR, GrupoPrioridade
from editais.triagem import Produto


def test_score_e_a_maior_similaridade_entre_qualquer_chunk_e_qualquer_produto() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        mapa = {"chunk um": [1.0, 0.0], "chunk dois": [0.0, 1.0]}
        return [mapa[t] for t in textos]

    perfil = [
        Produto(nome="A", vetor=[3.0, 4.0]),
        Produto(nome="B", vetor=[4.0, 3.0]),
    ]
    chunks_por_edital = {"X-1": ["chunk um", "chunk dois"]}

    resultado = calcular_scores_aderencia(chunks_por_edital, embedder, perfil, [])

    assert len(resultado) == 1
    assert resultado[0].numero_controle_pncp == "X-1"
    # Pares de cosseno: (um,A)=0.6 (um,B)=0.8 (dois,A)=0.8 (dois,B)=0.6.
    # Max pooling = 0.8; o primeiro a atingir 0.8 no varrimento e (um, B).
    assert resultado[0].score_aderencia == pytest.approx(0.8)
    assert resultado[0].produto_mais_proximo == "B"


def test_embedda_um_edital_por_vez_para_isolar_falhas_e_cachear_incremental() -> None:
    chamadas: list[list[str]] = []

    def embedder(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[1.0, 0.0] for _ in textos]

    perfil = [Produto(nome="A", vetor=[1.0, 0.0])]
    chunks_por_edital = {"X-1": ["c1", "c2"], "X-2": ["c3"]}

    calcular_scores_aderencia(chunks_por_edital, embedder, perfil, [])

    assert chamadas == [["c1", "c2"], ["c3"]]


def test_pula_edital_com_falha_persistente_de_embedding_sem_derrubar_os_demais() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        if textos == ["chunk-problematico"]:
            raise RuntimeError("Falha ao embeddar lote após 5 tentativas (último status HTTP 429).")
        return [[1.0, 0.0] for _ in textos]

    perfil = [Produto(nome="A", vetor=[1.0, 0.0])]
    chunks_por_edital = {
        "X-1": ["chunk-ok-antes"],
        "X-2": ["chunk-problematico"],
        "X-3": ["chunk-ok-depois"],
    }

    resultado = calcular_scores_aderencia(chunks_por_edital, embedder, perfil, [])

    assert [s.numero_controle_pncp for s in resultado] == ["X-1", "X-3"]


def test_agrupa_scores_pelo_edital_de_origem_de_cada_chunk() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        mapa = {
            "a1": [1.0, 0.0],
            "a2": [1.0, 0.0],
            "b1": [0.0, 1.0],
        }
        return [mapa[t] for t in textos]

    perfil = [Produto(nome="P", vetor=[1.0, 0.0])]
    chunks_por_edital = {"A": ["a1", "a2"], "B": ["b1"]}

    resultado = calcular_scores_aderencia(chunks_por_edital, embedder, perfil, [])

    por_numero = {s.numero_controle_pncp: s.score_aderencia for s in resultado}
    assert por_numero["A"] == pytest.approx(1.0)
    assert por_numero["B"] == pytest.approx(0.0)


def test_edital_sem_chunks_recebe_score_zero() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in textos]

    perfil = [Produto(nome="A", vetor=[1.0, 0.0])]
    chunks_por_edital: dict[str, list[str]] = {"SEM-DOC": []}

    resultado = calcular_scores_aderencia(chunks_por_edital, embedder, perfil, [])

    assert resultado[0].numero_controle_pncp == "SEM-DOC"
    assert resultado[0].score_aderencia == 0.0
    assert resultado[0].produto_mais_proximo == ""


def test_chunk_classificado_baixa_e_excluido_mesmo_com_maior_cosseno_bruto() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        mapa = {
            "clausula de confidencialidade": [1.0, 0.0],
            "do objeto do sistema de saude": [0.6, 0.8],
        }
        return [mapa[t] for t in textos]

    # Contra o Perfil Aurora puro, o chunk de confidencialidade teria o maior
    # cosseno bruto (1.0 vs 0.6) — mas é classificado BAIXA e deve ser excluído,
    # deixando o chunk de objeto (INCLUIR) vencer o max pooling.
    perfil = [Produto(nome="Software de Gestão em Saúde", vetor=[1.0, 0.0])]
    perfil_prioridade = [
        GrupoPrioridade(nome=GRUPO_BAIXA, vetor=[1.0, 0.0]),
        GrupoPrioridade(nome=GRUPO_INCLUIR, vetor=[0.6, 0.8]),
    ]
    chunks_por_edital = {
        "X-1": ["clausula de confidencialidade", "do objeto do sistema de saude"]
    }

    resultado = calcular_scores_aderencia(
        chunks_por_edital, embedder, perfil, perfil_prioridade
    )

    assert resultado[0].score_aderencia == pytest.approx(0.6)


def test_precisa_reprocessar_quando_nunca_foi_processado() -> None:
    assert precisa_reprocessar("2026-07-06T00:10:42", None) is True


def test_precisa_reprocessar_quando_data_de_atualizacao_mudou() -> None:
    assert precisa_reprocessar("2026-07-08T09:00:00", "2026-07-06T00:10:42") is True


def test_nao_reprocessa_quando_data_de_atualizacao_e_a_mesma() -> None:
    assert precisa_reprocessar("2026-07-06T00:10:42", "2026-07-06T00:10:42") is False


def test_serializa_editais_incluindo_flag_de_selecao_para_revisao() -> None:
    editais = [
        EditalAnalisado("B", 0.9, "Q", True),
        EditalAnalisado("C", 0.7, "R", False),
    ]

    assert serializar_analise_profunda(editais) == [
        {
            "numeroControlePNCP": "B",
            "score_aderencia": 0.9,
            "produto_mais_proximo": "Q",
            "selecionado_para_revisao": True,
        },
        {
            "numeroControlePNCP": "C",
            "score_aderencia": 0.7,
            "produto_mais_proximo": "R",
            "selecionado_para_revisao": False,
        },
    ]


def test_top_n_revisao_marca_os_maiores_scores_e_ordena_por_score_decrescente() -> None:
    scores = [
        ScoreAderencia("A", 0.5, "P"),
        ScoreAderencia("B", 0.9, "P"),
        ScoreAderencia("C", 0.1, "P"),
        ScoreAderencia("D", 0.7, "P"),
    ]

    resultado = marcar_selecionados_para_revisao(scores, n=2)

    assert [
        (e.numero_controle_pncp, e.selecionado_para_revisao) for e in resultado
    ] == [("B", True), ("D", True), ("A", False), ("C", False)]


def test_top_n_revisao_marca_todos_quando_ha_menos_editais_que_o_corte() -> None:
    scores = [
        ScoreAderencia("A", 0.5, "P"),
        ScoreAderencia("B", 0.9, "P"),
    ]

    resultado = marcar_selecionados_para_revisao(scores, n=100)

    assert all(e.selecionado_para_revisao for e in resultado)


def test_top_n_revisao_preserva_ordem_estavel_em_empates() -> None:
    scores = [
        ScoreAderencia("A", 0.5, "P"),
        ScoreAderencia("B", 0.5, "P"),
        ScoreAderencia("C", 0.5, "P"),
    ]

    resultado = marcar_selecionados_para_revisao(scores, n=1)

    assert [e.numero_controle_pncp for e in resultado] == ["A", "B", "C"]
    assert [e.selecionado_para_revisao for e in resultado] == [True, False, False]
