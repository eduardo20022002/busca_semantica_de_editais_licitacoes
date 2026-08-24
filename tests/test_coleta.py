from editais.coleta import ErroPagina, ParametrosBusca, RespostaBusca, coletar_editais


def test_coleta_editais_de_uma_unica_pagina() -> None:
    def buscar(params: object) -> RespostaBusca:
        return RespostaBusca(
            status_code=200,
            corpo={
                "data": [{"numeroControlePNCP": "123-1-000001/2026"}],
                "totalPaginas": 1,
            },
        )

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=lambda segundos: None,
    )

    assert resultado.editais == [{"numeroControlePNCP": "123-1-000001/2026"}]
    assert resultado.erros == []


def test_coleta_pagina_por_todas_as_paginas_de_uma_modalidade() -> None:
    paginas_por_numero = {
        1: RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "pagina-1"}], "totalPaginas": 2},
        ),
        2: RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "pagina-2"}], "totalPaginas": 2},
        ),
    }

    def buscar(params: ParametrosBusca) -> RespostaBusca:
        return paginas_por_numero[params.pagina]

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=lambda segundos: None,
    )

    assert resultado.editais == [
        {"numeroControlePNCP": "pagina-1"},
        {"numeroControlePNCP": "pagina-2"},
    ]
    assert resultado.erros == []


def test_coleta_agrega_editais_de_varias_modalidades() -> None:
    def buscar(params: ParametrosBusca) -> RespostaBusca:
        return RespostaBusca(
            status_code=200,
            corpo={
                "data": [
                    {
                        "numeroControlePNCP": f"modalidade-{params.codigo_modalidade_contratacao}",
                    }
                ],
                "totalPaginas": 1,
            },
        )

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[4, 6],
        buscar=buscar,
        dormir=lambda segundos: None,
    )

    assert resultado.editais == [
        {"numeroControlePNCP": "modalidade-4"},
        {"numeroControlePNCP": "modalidade-6"},
    ]
    assert resultado.erros == []


def test_coleta_tenta_de_novo_apos_limite_de_requisicoes_excedido() -> None:
    respostas = [
        RespostaBusca(status_code=429, corpo=None),
        RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "sucesso-na-segunda-tentativa"}], "totalPaginas": 1},
        ),
    ]

    def buscar(params: ParametrosBusca) -> RespostaBusca:
        return respostas.pop(0)

    esperas_registradas: list[float] = []

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=esperas_registradas.append,
    )

    assert resultado.editais == [{"numeroControlePNCP": "sucesso-na-segunda-tentativa"}]
    assert resultado.erros == []
    assert esperas_registradas == [2.0]


def test_coleta_registra_erro_e_segue_quando_pagina_falha_persistentemente() -> None:
    def buscar(params: ParametrosBusca) -> RespostaBusca:
        return RespostaBusca(status_code=429, corpo=None)

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=lambda segundos: None,
        max_tentativas=2,
    )

    assert resultado.editais == []
    assert resultado.erros == [
        ErroPagina(modalidade=6, pagina=1, motivo="limite de requisições excedido após retries")
    ]


def test_coleta_segue_para_proxima_modalidade_apos_falha_persistente() -> None:
    def buscar(params: ParametrosBusca) -> RespostaBusca:
        if params.codigo_modalidade_contratacao == 4:
            return RespostaBusca(status_code=429, corpo=None)
        return RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "veio-da-modalidade-6"}], "totalPaginas": 1},
        )

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[4, 6],
        buscar=buscar,
        dormir=lambda segundos: None,
        max_tentativas=2,
    )

    assert resultado.editais == [{"numeroControlePNCP": "veio-da-modalidade-6"}]
    assert resultado.erros == [
        ErroPagina(modalidade=4, pagina=1, motivo="limite de requisições excedido após retries")
    ]


def test_coleta_continua_paginas_seguintes_apos_falha_persistente_no_meio() -> None:
    respostas_por_pagina = {
        1: RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "pagina-1"}], "totalPaginas": 3},
        ),
        3: RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "pagina-3"}], "totalPaginas": 3},
        ),
    }

    def buscar(params: ParametrosBusca) -> RespostaBusca:
        if params.pagina == 2:
            return RespostaBusca(status_code=429, corpo=None)
        return respostas_por_pagina[params.pagina]

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=lambda segundos: None,
        max_tentativas=1,
    )

    assert resultado.editais == [
        {"numeroControlePNCP": "pagina-1"},
        {"numeroControlePNCP": "pagina-3"},
    ]
    assert resultado.erros == [
        ErroPagina(modalidade=6, pagina=2, motivo="limite de requisições excedido após retries")
    ]


def test_coleta_respeita_intervalo_minimo_entre_requisicoes_bem_sucedidas() -> None:
    def buscar(params: ParametrosBusca) -> RespostaBusca:
        return RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": f"pagina-{params.pagina}"}], "totalPaginas": 3},
        )

    esperas_registradas: list[float] = []

    coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=esperas_registradas.append,
        intervalo_minimo_segundos=1.0,
    )

    assert esperas_registradas == [1.0, 1.0]


def test_coleta_nao_aplica_intervalo_minimo_apos_a_ultima_requisicao() -> None:
    def buscar(params: ParametrosBusca) -> RespostaBusca:
        return RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "unica-pagina"}], "totalPaginas": 1},
        )

    esperas_registradas: list[float] = []

    coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=esperas_registradas.append,
        intervalo_minimo_segundos=1.0,
    )

    assert esperas_registradas == []


def test_coleta_faz_uma_unica_requisicao_para_modalidade_sem_resultados() -> None:
    chamadas: list[ParametrosBusca] = []

    def buscar(params: ParametrosBusca) -> RespostaBusca:
        chamadas.append(params)
        return RespostaBusca(status_code=200, corpo={"data": [], "totalPaginas": 0})

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=lambda segundos: None,
    )

    assert resultado.editais == []
    assert resultado.erros == []
    assert len(chamadas) == 1


def test_coleta_tenta_de_novo_apos_erro_transitorio_de_servidor() -> None:
    respostas = [
        RespostaBusca(status_code=503, corpo=None),
        RespostaBusca(
            status_code=200,
            corpo={"data": [{"numeroControlePNCP": "sucesso-apos-503"}], "totalPaginas": 1},
        ),
    ]

    def buscar(params: ParametrosBusca) -> RespostaBusca:
        return respostas.pop(0)

    resultado = coletar_editais(
        data_inicial="20260716",
        data_final="20260716",
        modalidades=[6],
        buscar=buscar,
        dormir=lambda segundos: None,
    )

    assert resultado.editais == [{"numeroControlePNCP": "sucesso-apos-503"}]
    assert resultado.erros == []
