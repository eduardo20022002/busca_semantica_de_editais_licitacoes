from editais.chunking import (
    CHUNK_ALVO_CARACTERES,
    MINIMO_SECOES_PARA_SUSPEITA,
    chunkar_texto,
)


def test_divide_por_secao_estrutural_reconhecida() -> None:
    texto = (
        "DO OBJETO\n"
        + "Contratacao de sistema de gestao hospitalar. " * 5
        + "\nESPECIFICACOES TECNICAS\n"
        + "Requisitos de interoperabilidade HL7 e FHIR. " * 5
    )

    chunks = chunkar_texto(texto)

    assert any("DO OBJETO" in c and "ESPECIFICACOES TECNICAS" not in c for c in chunks)
    assert any("ESPECIFICACOES TECNICAS" in c and "DO OBJETO" not in c for c in chunks)


def test_texto_sem_cabecalho_usa_janela_deslizante_com_sobreposicao() -> None:
    texto = "palavra " * 2000  # ~16000 caracteres, sem cabecalhos

    chunks = chunkar_texto(texto)

    assert len(chunks) >= 2
    # Chunks consecutivos se sobrepoem: um trecho do fim de um aparece no comeco
    # do proximo.
    sufixo = chunks[0][-100:]
    assert sufixo in chunks[1]


def test_secao_maior_que_o_alvo_e_subdividida() -> None:
    texto = "DO OBJETO\n" + "detalhamento tecnico do objeto contratado. " * 500

    chunks = chunkar_texto(texto)

    assert len(chunks) >= 2
    assert all(len(c) <= CHUNK_ALVO_CARACTERES + 1000 for c in chunks)


def test_chunk_curto_demais_e_descartado() -> None:
    assert chunkar_texto("DO OBJETO\nab") == []


def test_texto_vazio_ou_espacos_retorna_lista_vazia() -> None:
    assert chunkar_texto("") == []
    assert chunkar_texto("   \n\t  ") == []


def test_todo_o_conteudo_relevante_aparece_em_algum_chunk() -> None:
    texto = "DO OBJETO\n" + "conteudo importante sobre telemedicina que deve ser preservado."

    chunks = chunkar_texto(texto)

    assert any("telemedicina" in c for c in chunks)


def _lista_de_itens(quantidade: int) -> str:
    # Reproduz o formato real que quebrava o chunker: cada linha de uma lista de
    # materiais parece cabeçalho (curta e maiúscula) para a heurística.
    return "\n".join(
        f"{n} 6 UN AFASTADOR ANAL BIVALVE SEM CABO - DE ACO INOX" for n in range(quantidade)
    )


def test_lista_tabular_nao_vira_um_chunk_por_linha() -> None:
    # Achado real (edital 11259476000168-1-000097/2026): uma lista de materiais
    # hospitalares dentro do PDF do Edital gerou 3.759 Chunks de ~138 chars —
    # um por item. Outro edital chegou a 19.779 Chunks e travou a Etapa 2.
    linhas = MINIMO_SECOES_PARA_SUSPEITA * 3
    texto = _lista_de_itens(linhas)

    chunks = chunkar_texto(texto)

    assert len(chunks) < linhas / 10
    # O conteúdo continua lá, só agrupado em blocos maiores em vez de 1 por linha.
    assert any("AFASTADOR ANAL BIVALVE" in c for c in chunks)


def test_documento_curto_com_linhas_curtas_nao_dispara_o_fallback() -> None:
    # Média baixa isolada NÃO é sinal de fragmentação degenerada: editais curtos
    # (4 a 22 Chunks na amostra real) têm média baixa e devem manter as seções.
    texto = (
        "DO OBJETO\nContratacao de sistema informatizado de gestao em saude.\n"
        "DA VIGENCIA\nO contrato tera vigencia de doze meses contados da assinatura."
    )

    chunks = chunkar_texto(texto)

    assert any("DO OBJETO" in c and "DA VIGENCIA" not in c for c in chunks)


def test_prosa_longa_com_muitas_secoes_reais_mantem_as_fronteiras() -> None:
    # Muitas seções por si só não bastam: se cada uma tem prosa de verdade, a
    # média fica alta e a heurística de cabeçalho continua valendo.
    texto = "".join(
        f"SECAO NUMERO {n}\n" + ("texto corrido com conteudo relevante do edital. " * 20) + "\n"
        for n in range(MINIMO_SECOES_PARA_SUSPEITA + 50)
    )

    chunks = chunkar_texto(texto)

    assert any("SECAO NUMERO 0" in c and "SECAO NUMERO 1\n" not in c for c in chunks)
