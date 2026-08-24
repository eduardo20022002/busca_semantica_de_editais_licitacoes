from editais.prioridade import (
    GRUPO_BAIXA,
    GRUPO_INCLUIR,
    GrupoPrioridade,
    classificar_chunk,
    extrair_unidades_de_prioridade,
)


def test_extrai_bullets_ignorando_titulo_e_introducao() -> None:
    markdown = """# Prioridade BAIXA

Trechos que não descrevem o objeto contratado.

- Condições de habilitação e documentação jurídica
- Garantias contratuais, penalidades e sanções administrativas
"""

    assert extrair_unidades_de_prioridade(markdown) == [
        "Condições de habilitação e documentação jurídica",
        "Garantias contratuais, penalidades e sanções administrativas",
    ]


def test_classifica_baixa_quando_similaridade_e_estritamente_maior() -> None:
    perfil = [
        GrupoPrioridade(nome=GRUPO_BAIXA, vetor=[1.0, 0.0]),
        GrupoPrioridade(nome=GRUPO_INCLUIR, vetor=[0.0, 1.0]),
    ]

    assert classificar_chunk([1.0, 0.0], perfil) == GRUPO_BAIXA


def test_classifica_incluir_quando_similaridade_e_maior() -> None:
    perfil = [
        GrupoPrioridade(nome=GRUPO_BAIXA, vetor=[1.0, 0.0]),
        GrupoPrioridade(nome=GRUPO_INCLUIR, vetor=[0.0, 1.0]),
    ]

    assert classificar_chunk([0.0, 1.0], perfil) == GRUPO_INCLUIR


def test_classifica_incluir_em_caso_de_empate() -> None:
    perfil = [
        GrupoPrioridade(nome=GRUPO_BAIXA, vetor=[1.0, 1.0]),
        GrupoPrioridade(nome=GRUPO_INCLUIR, vetor=[1.0, 1.0]),
    ]

    assert classificar_chunk([1.0, 1.0], perfil) == GRUPO_INCLUIR


def test_classifica_incluir_quando_perfil_de_prioridade_esta_vazio() -> None:
    assert classificar_chunk([1.0, 0.0], []) == GRUPO_INCLUIR


def test_usa_o_melhor_vetor_de_cada_grupo_quando_ha_mais_de_um() -> None:
    perfil = [
        GrupoPrioridade(nome=GRUPO_BAIXA, vetor=[0.6, 0.8]),
        GrupoPrioridade(nome=GRUPO_INCLUIR, vetor=[0.0, 1.0]),
        GrupoPrioridade(nome=GRUPO_INCLUIR, vetor=[1.0, 0.0]),
    ]

    # Só o segundo vetor de "incluir" bate com o chunk (cosseno 1.0) — se a
    # função considerasse só o primeiro vetor de cada grupo (cosseno 0.0),
    # "baixa" venceria (0.6) por engano.
    assert classificar_chunk([1.0, 0.0], perfil) == GRUPO_INCLUIR


# Fixtures de texto real rotuladas à mão na validação empírica desta spec
# (ADR-0005): simula com vetores fake o resultado já observado embeddando o
# texto de verdade contra o Perfil de Prioridade real.
def test_clausula_de_confidencialidade_do_tre_rj_classifica_baixa() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        mapa = {
            "TERMO DE COMPROMISSO DE MANUTENÇÃO DE SIGILO E CONFIDENCIALIDADE": [1.0, 0.0],
            "confidencialidade e sigilo": [1.0, 0.0],
            "objeto e especificações técnicas": [0.0, 1.0],
        }
        return [mapa[t] for t in textos]

    perfil = [
        GrupoPrioridade(nome=GRUPO_BAIXA, vetor=embedder(["confidencialidade e sigilo"])[0]),
        GrupoPrioridade(
            nome=GRUPO_INCLUIR, vetor=embedder(["objeto e especificações técnicas"])[0]
        ),
    ]
    vetor_chunk = embedder(
        ["TERMO DE COMPROMISSO DE MANUTENÇÃO DE SIGILO E CONFIDENCIALIDADE"]
    )[0]

    assert classificar_chunk(vetor_chunk, perfil) == GRUPO_BAIXA


def test_clausula_de_lgpd_dos_exames_laboratoriais_classifica_baixa() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        mapa = {
            "CLÁUSULA 13ª - DA PROTEÇÃO E TRANSMISSÃO DE INFORMAÇÃO, DADOS PESSOAIS": [
                1.0,
                0.0,
            ],
            "proteção de dados pessoais e LGPD": [1.0, 0.0],
            "objeto e especificações técnicas": [0.0, 1.0],
        }
        return [mapa[t] for t in textos]

    perfil = [
        GrupoPrioridade(nome=GRUPO_BAIXA, vetor=embedder(["proteção de dados pessoais e LGPD"])[0]),
        GrupoPrioridade(
            nome=GRUPO_INCLUIR, vetor=embedder(["objeto e especificações técnicas"])[0]
        ),
    ]
    vetor_chunk = embedder(
        ["CLÁUSULA 13ª - DA PROTEÇÃO E TRANSMISSÃO DE INFORMAÇÃO, DADOS PESSOAIS"]
    )[0]

    assert classificar_chunk(vetor_chunk, perfil) == GRUPO_BAIXA


def test_secao_do_objeto_classifica_incluir() -> None:
    def embedder(textos: list[str]) -> list[list[float]]:
        mapa = {
            "DO OBJETO: contratação de sistema de prontuário eletrônico": [0.0, 1.0],
            "condições de habilitação e documentação jurídica": [1.0, 0.0],
            "objeto e especificações técnicas": [0.0, 1.0],
        }
        return [mapa[t] for t in textos]

    perfil = [
        GrupoPrioridade(
            nome=GRUPO_BAIXA, vetor=embedder(["condições de habilitação e documentação jurídica"])[0]
        ),
        GrupoPrioridade(
            nome=GRUPO_INCLUIR, vetor=embedder(["objeto e especificações técnicas"])[0]
        ),
    ]
    vetor_chunk = embedder(["DO OBJETO: contratação de sistema de prontuário eletrônico"])[0]

    assert classificar_chunk(vetor_chunk, perfil) == GRUPO_INCLUIR
