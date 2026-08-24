from editais.base_teste import montar_base


def test_monta_base_pareando_cada_edital_com_seu_embedding() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in textos]

    editais = [
        {"numeroControlePNCP": "X-1", "objetoCompra": "abc", "modalidadeNome": "Pregão"},
        {"numeroControlePNCP": "X-2", "objetoCompra": "de"},
    ]

    base = montar_base(editais, embedder)

    assert base == [
        {"numeroControlePNCP": "X-1", "objetoCompra": "abc", "embedding": [3.0]},
        {"numeroControlePNCP": "X-2", "objetoCompra": "de", "embedding": [2.0]},
    ]


def test_embedda_todos_os_objetos_numa_unica_chamada() -> None:
    chamadas: list[list[str]] = []

    def embedder(textos: list[str]) -> list[list[float]]:
        chamadas.append(list(textos))
        return [[1.0] for _ in textos]

    editais = [
        {"numeroControlePNCP": "X-1", "objetoCompra": "objeto 1"},
        {"numeroControlePNCP": "X-2", "objetoCompra": "objeto 2"},
    ]

    montar_base(editais, embedder)

    assert chamadas == [["objeto 1", "objeto 2"]]
