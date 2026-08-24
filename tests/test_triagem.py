from pathlib import Path

import pytest

from editais.triagem import (
    Produto,
    ScoreTriagem,
    calcular_scores_triagem,
    carregar_perfil,
    marcar_selecionados,
)


def test_score_e_a_maior_similaridade_entre_o_edital_e_os_produtos() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        mapa = {"objeto do edital X": [3.0, 4.0]}
        return [mapa[t] for t in textos]

    perfil = [
        Produto(nome="A", vetor=[1.0, 0.0]),
        Produto(nome="B", vetor=[0.0, 1.0]),
    ]
    editais = [{"numeroControlePNCP": "X-1", "objetoCompra": "objeto do edital X"}]

    resultado = calcular_scores_triagem(editais, embedder, perfil)

    assert len(resultado) == 1
    assert resultado[0].numero_controle_pncp == "X-1"
    # cosseno([3,4],[1,0]) = 0.6 ; cosseno([3,4],[0,1]) = 0.8 → max = 0.8, produto B
    assert resultado[0].produto_mais_proximo == "B"
    assert resultado[0].score_triagem == pytest.approx(0.8)


def test_embedda_todos_os_objetos_numa_unica_chamada_em_lote() -> None:
    chamadas: list[list[str]] = []

    def embedder(textos: list[str]) -> list[list[float]]:
        chamadas.append(textos)
        return [[1.0, 0.0] for _ in textos]

    perfil = [Produto(nome="A", vetor=[1.0, 0.0])]
    editais = [
        {"numeroControlePNCP": "X-1", "objetoCompra": "objeto 1"},
        {"numeroControlePNCP": "X-2", "objetoCompra": "objeto 2"},
        {"numeroControlePNCP": "X-3", "objetoCompra": "objeto 3"},
    ]

    resultado = calcular_scores_triagem(editais, embedder, perfil)

    assert [s.numero_controle_pncp for s in resultado] == ["X-1", "X-2", "X-3"]
    assert chamadas == [["objeto 1", "objeto 2", "objeto 3"]]


def test_top_n_marca_os_maiores_scores_e_ordena_por_score_decrescente() -> None:
    scores = [
        ScoreTriagem("A", 0.5, "P"),
        ScoreTriagem("B", 0.9, "P"),
        ScoreTriagem("C", 0.1, "P"),
        ScoreTriagem("D", 0.7, "P"),
    ]

    resultado = marcar_selecionados(scores, n=2)

    assert [
        (e.numero_controle_pncp, e.selecionado_para_analise_profunda) for e in resultado
    ] == [("B", True), ("D", True), ("A", False), ("C", False)]


def test_top_n_marca_todos_quando_ha_menos_editais_que_o_corte() -> None:
    scores = [
        ScoreTriagem("A", 0.5, "P"),
        ScoreTriagem("B", 0.9, "P"),
    ]

    resultado = marcar_selecionados(scores, n=100)

    assert all(e.selecionado_para_analise_profunda for e in resultado)


def test_top_n_preserva_ordem_estavel_em_empates() -> None:
    scores = [
        ScoreTriagem("A", 0.5, "P"),
        ScoreTriagem("B", 0.5, "P"),
        ScoreTriagem("C", 0.5, "P"),
    ]

    resultado = marcar_selecionados(scores, n=1)

    assert [e.numero_controle_pncp for e in resultado] == ["A", "B", "C"]
    assert [e.selecionado_para_analise_profunda for e in resultado] == [True, False, False]


def _markdown_produto(titulo: str, bullets: list[str], termos: str | None) -> str:
    linhas = [f"# {titulo}", "", f"Introdução qualquer sobre {titulo}.", "", "## Aplicações típicas", ""]
    linhas += [f"- {bullet}" for bullet in bullets]
    if termos is not None:
        linhas += ["", "## Tecnologias e termos relacionados", "", termos]
    return "\n".join(linhas)


def _escrever_produto(diretorio: Path, nome_arquivo: str, conteudo: str) -> None:
    (diretorio / nome_arquivo).write_text(conteudo, encoding="utf-8")


def test_primeira_carga_embedda_uma_unidade_por_aplicacao_e_por_termos(tmp_path: Path) -> None:
    _escrever_produto(
        tmp_path, "a.md", _markdown_produto("A", ["Bullet 1", "Bullet 2"], "termo1, termo2")
    )
    _escrever_produto(tmp_path, "b.md", _markdown_produto("B", ["Bullet único"], None))

    chamadas: list[list[str]] = []

    def embedder(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[float(len(t)), 1.0] for t in textos]

    perfil = carregar_perfil(tmp_path, embedder, modelo="modelo-teste")

    assert [(p.nome, p.vetor) for p in perfil] == [
        ("a", [8.0, 1.0]),
        ("a", [8.0, 1.0]),
        ("a", [len("termo1, termo2"), 1.0]),
        ("b", [len("Bullet único"), 1.0]),
    ]
    assert chamadas == [
        ["Bullet 1", "Bullet 2", "termo1, termo2"],
        ["Bullet único"],
    ]


def test_segunda_carga_usa_cache_sem_reembeddar(tmp_path: Path) -> None:
    _escrever_produto(tmp_path, "a.md", _markdown_produto("A", ["Bullet 1"], "termo1"))

    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0] for t in textos]

    perfil_primeira = carregar_perfil(tmp_path, embedder, modelo="modelo-teste")

    chamadas_segunda: list[list[str]] = []

    def embedder_segunda(textos: list[str]) -> list[list[float]]:
        chamadas_segunda.append(list(textos))
        return [[float(len(t)), 1.0] for t in textos]

    perfil_segunda = carregar_perfil(tmp_path, embedder_segunda, modelo="modelo-teste")

    assert chamadas_segunda == []
    assert perfil_segunda == perfil_primeira


def test_alteracao_de_conteudo_reembedda_so_o_arquivo_alterado(tmp_path: Path) -> None:
    _escrever_produto(tmp_path, "a.md", _markdown_produto("A", ["Bullet 1"], "termo1"))
    _escrever_produto(tmp_path, "b.md", _markdown_produto("B", ["Bullet único"], None))

    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0] for t in textos]

    carregar_perfil(tmp_path, embedder, modelo="modelo-teste")

    _escrever_produto(tmp_path, "a.md", _markdown_produto("A", ["Bullet alterado"], "termo1"))

    chamadas_terceira: list[list[str]] = []

    def embedder_terceira(textos: list[str]) -> list[list[float]]:
        chamadas_terceira.append(list(textos))
        return [[float(len(t)), 2.0] for t in textos]

    perfil = carregar_perfil(tmp_path, embedder_terceira, modelo="modelo-teste")

    assert chamadas_terceira == [["Bullet alterado", "termo1"]]
    assert [(p.nome, p.vetor) for p in perfil] == [
        ("a", [len("Bullet alterado"), 2.0]),
        ("a", [len("termo1"), 2.0]),
        ("b", [len("Bullet único"), 1.0]),
    ]


def test_serializar_triagem_usa_chaves_camelcase_como_na_entrada() -> None:
    from editais.triagem import EditalTriado, serializar_triagem

    editais_triados = [
        EditalTriado(
            numero_controle_pncp="X-1",
            score_triagem=0.8,
            produto_mais_proximo="B",
            selecionado_para_analise_profunda=True,
        )
    ]

    assert serializar_triagem(editais_triados) == [
        {
            "numeroControlePNCP": "X-1",
            "score_triagem": 0.8,
            "produto_mais_proximo": "B",
            "selecionado_para_analise_profunda": True,
        }
    ]

def test_extrai_bullets_e_termos_relacionados_sem_a_introducao() -> None:
    from editais.triagem import extrair_unidades_de_texto

    markdown = """# IA para Saúde

A Aurora desenvolve soluções de inteligência artificial aplicadas à saúde.

## Aplicações típicas

- Triagem inteligente de pacientes
- Diagnóstico assistido por imagem

## Tecnologias e termos relacionados

Inteligência artificial, machine learning, deep learning.
"""

    unidades = extrair_unidades_de_texto(markdown)

    assert unidades == [
        "Triagem inteligente de pacientes",
        "Diagnóstico assistido por imagem",
        "Inteligência artificial, machine learning, deep learning.",
    ]


def test_extrai_apenas_bullets_quando_nao_ha_secao_de_termos() -> None:
    from editais.triagem import extrair_unidades_de_texto

    markdown = """# Produto X

Introdução qualquer.

## Aplicações típicas

- Caso de uso único
"""

    unidades = extrair_unidades_de_texto(markdown)

    assert unidades == ["Caso de uso único"]


def test_embedder_com_cache_chama_o_embedder_real_na_primeira_vez(tmp_path: Path) -> None:
    from editais.triagem import criar_embedder_com_cache

    chamadas: list[list[str]] = []

    def embedder_real(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[float(len(t))] for t in textos]

    embedder_cacheado = criar_embedder_com_cache(embedder_real, tmp_path / "cache.json", modelo="modelo-teste")

    vetores = embedder_cacheado(["abc", "de"])

    assert vetores == [[3.0], [2.0]]
    assert chamadas == [["abc", "de"]]


def test_embedder_com_cache_nao_chama_o_embedder_real_para_textos_ja_vistos(
    tmp_path: Path,
) -> None:
    from editais.triagem import criar_embedder_com_cache

    def embedder_real(textos: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in textos]

    caminho_cache = tmp_path / "cache.json"
    embedder_cacheado_primeira = criar_embedder_com_cache(embedder_real, caminho_cache, modelo="modelo-teste")
    embedder_cacheado_primeira(["abc", "de"])

    chamadas_segunda: list[list[str]] = []

    def embedder_real_segunda(textos: list[str]) -> list[list[float]]:
        chamadas_segunda.append(list(textos))
        return [[float(len(t))] for t in textos]

    embedder_cacheado_segunda = criar_embedder_com_cache(embedder_real_segunda, caminho_cache, modelo="modelo-teste")
    vetores = embedder_cacheado_segunda(["abc", "de"])

    assert vetores == [[3.0], [2.0]]
    assert chamadas_segunda == []


def test_embedder_com_cache_so_chama_o_embedder_real_para_textos_novos(tmp_path: Path) -> None:
    from editais.triagem import criar_embedder_com_cache

    def embedder_real(textos: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in textos]

    caminho_cache = tmp_path / "cache.json"
    criar_embedder_com_cache(embedder_real, caminho_cache, modelo="modelo-teste")(["abc", "de"])

    chamadas_segunda: list[list[str]] = []

    def embedder_real_segunda(textos: list[str]) -> list[list[float]]:
        chamadas_segunda.append(list(textos))
        return [[float(len(t))] for t in textos]

    embedder_cacheado = criar_embedder_com_cache(embedder_real_segunda, caminho_cache, modelo="modelo-teste")
    vetores = embedder_cacheado(["abc", "novo-texto"])

    assert vetores == [[3.0], [10.0]]
    assert chamadas_segunda == [["novo-texto"]]


def test_perfil_reembedda_quando_o_modelo_muda(tmp_path: Path) -> None:
    _escrever_produto(tmp_path, "a.md", _markdown_produto("A", ["Bullet 1"], "termo1"))

    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0] for t in textos]

    carregar_perfil(tmp_path, embedder, modelo="modelo-antigo")

    chamadas: list[list[str]] = []

    def embedder_novo(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[float(len(t)), 9.0] for t in textos]

    perfil = carregar_perfil(tmp_path, embedder_novo, modelo="modelo-novo")

    assert chamadas == [["Bullet 1", "termo1"]]
    assert [p.vetor for p in perfil] == [[len("Bullet 1"), 9.0], [len("termo1"), 9.0]]


def test_embedder_com_cache_persiste_grupos_ja_embeddados_quando_um_grupo_falha(
    tmp_path: Path,
) -> None:
    from editais.triagem import criar_embedder_com_cache

    chamadas: list[list[str]] = []

    def embedder_que_falha_no_segundo_grupo(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        if len(chamadas) == 2:
            raise RuntimeError("rate limit persistente")
        return [[float(len(t))] for t in textos]

    caminho_cache = tmp_path / "cache.json"
    embedder_cacheado = criar_embedder_com_cache(
        embedder_que_falha_no_segundo_grupo,
        caminho_cache,
        modelo="modelo-teste",
        textos_por_persistencia=1,
    )

    with pytest.raises(RuntimeError):
        embedder_cacheado(["abc", "de"])

    # O primeiro grupo (já embeddado com sucesso) precisa ter sido persistido —
    # a retomada só deve reembeddar o que falhou.
    chamadas_retomada: list[list[str]] = []

    def embedder_retomada(textos: list[str]) -> list[list[float]]:
        chamadas_retomada.append(list(textos))
        return [[float(len(t))] for t in textos]

    embedder_cacheado_retomada = criar_embedder_com_cache(
        embedder_retomada, caminho_cache, modelo="modelo-teste"
    )
    vetores = embedder_cacheado_retomada(["abc", "de"])

    assert chamadas_retomada == [["de"]]
    assert vetores == [[3.0], [2.0]]


def test_embedder_com_cache_embedda_em_grupos_do_tamanho_configurado(tmp_path: Path) -> None:
    from editais.triagem import criar_embedder_com_cache

    chamadas: list[list[str]] = []

    def embedder_real(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[float(len(t))] for t in textos]

    embedder_cacheado = criar_embedder_com_cache(
        embedder_real, tmp_path / "cache.json", modelo="modelo-teste", textos_por_persistencia=2
    )

    vetores = embedder_cacheado(["a", "bb", "ccc"])

    assert chamadas == [["a", "bb"], ["ccc"]]
    assert vetores == [[1.0], [2.0], [3.0]]


def test_embedder_com_cache_anexa_em_vez_de_reescrever_o_arquivo(tmp_path: Path) -> None:
    # Achado real (2026-08-11): reescrever o arquivo inteiro a cada
    # persistência fazia o custo por edital depender do tamanho do cache
    # acumulado, não do que havia de novo. Com o cache de Chunks em 1,19 GB,
    # cada edital levava ~100s para gravar ~2,7 MB de vetores novos.
    from editais.triagem import criar_embedder_com_cache

    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in textos]

    caminho_cache = tmp_path / "cache.jsonl"
    criar_embedder_com_cache(embedder, caminho_cache, modelo="modelo-teste")(["abc"])
    conteudo_inicial = caminho_cache.read_bytes()

    criar_embedder_com_cache(embedder, caminho_cache, modelo="modelo-teste")(["abc", "de"])
    conteudo_final = caminho_cache.read_bytes()

    # Os bytes já gravados permanecem intocados — só o vetor novo é anexado.
    assert conteudo_final.startswith(conteudo_inicial)
    assert len(conteudo_final.splitlines()) == 2


def test_embedder_com_cache_reembedda_quando_o_modelo_muda(tmp_path: Path) -> None:
    from editais.triagem import criar_embedder_com_cache

    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in textos]

    caminho_cache = tmp_path / "cache.json"
    criar_embedder_com_cache(embedder, caminho_cache, modelo="modelo-antigo")(["abc"])

    chamadas: list[list[str]] = []

    def embedder_novo(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[float(len(t)) * 2] for t in textos]

    vetores = criar_embedder_com_cache(embedder_novo, caminho_cache, modelo="modelo-novo")(["abc"])

    assert chamadas == [["abc"]]
    assert vetores == [[6.0]]


def test_embedder_com_cache_para_ao_estourar_o_orcamento_de_tempo(tmp_path: Path) -> None:
    # Achado real: um edital de 19.779 Chunks segurou a Etapa 2 por mais de 15
    # minutos. O orçamento corta entre grupos e levanta RuntimeError, que
    # calcular_scores_aderencia já trata pulando o edital.
    from editais.triagem import criar_embedder_com_cache

    chamadas: list[list[str]] = []

    def embedder(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[float(len(t))] for t in textos]

    # Relógio falso: cada leitura avança 10s, então o orçamento de 15s estoura
    # antes do terceiro grupo.
    tempos = iter([0.0, 10.0, 20.0, 30.0, 40.0, 50.0])

    embedder_cacheado = criar_embedder_com_cache(
        embedder,
        tmp_path / "cache.json",
        modelo="modelo-teste",
        textos_por_persistencia=1,
        segundos_maximos_por_chamada=15.0,
        relogio=lambda: next(tempos),
    )

    with pytest.raises(RuntimeError, match="orçamento"):
        embedder_cacheado(["a", "bb", "ccc", "dddd"])

    # O que rodou antes do corte foi embeddado — não se perde na reexecução.
    assert chamadas == [["a"], ["bb"]]


def test_embedder_com_cache_persiste_o_progresso_antes_do_corte(tmp_path: Path) -> None:
    from editais.triagem import criar_embedder_com_cache

    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in textos]

    caminho_cache = tmp_path / "cache.json"
    tempos = iter([0.0, 10.0, 20.0, 30.0, 40.0])

    with pytest.raises(RuntimeError):
        criar_embedder_com_cache(
            embedder,
            caminho_cache,
            modelo="modelo-teste",
            textos_por_persistencia=1,
            segundos_maximos_por_chamada=5.0,
            relogio=lambda: next(tempos),
        )(["abc", "de"])

    # Uma reexecução aproveita o que já foi gravado em disco.
    chamadas: list[list[str]] = []

    def embedder_segunda(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[float(len(t))] for t in textos]

    vetores = criar_embedder_com_cache(
        embedder_segunda, caminho_cache, modelo="modelo-teste"
    )(["abc", "de"])

    assert chamadas == [["de"]]  # "abc" veio do cache gravado antes do corte
    assert vetores == [[3.0], [2.0]]


def test_embedder_com_cache_nao_corta_quando_esta_dentro_do_orcamento(tmp_path: Path) -> None:
    from editais.triagem import criar_embedder_com_cache

    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in textos]

    vetores = criar_embedder_com_cache(
        embedder,
        tmp_path / "cache.json",
        modelo="modelo-teste",
        textos_por_persistencia=1,
        segundos_maximos_por_chamada=1000.0,
        relogio=iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0]).__next__,
    )(["abc", "de", "f"])

    assert vetores == [[3.0], [2.0], [1.0]]
