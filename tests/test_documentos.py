from editais.documentos import (
    ArquivoBaixado,
    ArquivoEdital,
    RespostaArquivos,
    RespostaDownload,
    baixar_arquivo,
    listar_arquivos,
    nome_de_arquivo_seguro,
    selecionar_documentos_principais,
)


def _arquivo(sequencial: int, tipo: str) -> ArquivoEdital:
    return ArquivoEdital(
        sequencial_documento=sequencial,
        titulo=f"arquivo-{sequencial}",
        tipo_documento_nome=tipo,
        url=f"u{sequencial}",
        data_publicacao_pncp="2026-07-06T00:10:37",
    )


def test_seleciona_edital_e_termo_de_referencia() -> None:
    edital = _arquivo(1, "Edital")
    tr = _arquivo(2, "Termo de Referência")
    outros = _arquivo(3, "Outros Documentos")

    assert selecionar_documentos_principais([edital, tr, outros]) == [edital, tr]


def test_sem_termo_de_referencia_usa_projeto_basico() -> None:
    edital = _arquivo(1, "Edital")
    projeto_basico = _arquivo(2, "Projeto Básico")

    assert selecionar_documentos_principais([edital, projeto_basico]) == [
        edital,
        projeto_basico,
    ]


def test_so_com_estudo_tecnico_preliminar_usa_etp() -> None:
    etp = _arquivo(1, "Estudo Técnico Preliminar")
    outros = _arquivo(2, "Outros Documentos")

    assert selecionar_documentos_principais([etp, outros]) == [etp]


def test_sem_tipo_canonico_cai_para_outros_documentos() -> None:
    # Achado real (amostra de 100 editais): 7 não publicavam Edital nem TR, só
    # "Outros Documentos" — e o edital de verdade estava lá dentro. Antes desta
    # cadeia de última instância eles produziam zero Chunk e sumiam do funil.
    outros_1 = _arquivo(1, "Outros Documentos")
    outros_2 = _arquivo(2, "Outros Documentos")

    assert selecionar_documentos_principais([outros_1, outros_2]) == [outros_1, outros_2]


def test_ultima_instancia_prefere_dfd_a_outros_documentos() -> None:
    dfd = _arquivo(1, "DFD")
    outros = _arquivo(2, "Outros Documentos")

    assert selecionar_documentos_principais([dfd, outros]) == [dfd]


def test_ultima_instancia_so_vale_sem_nenhum_tipo_canonico() -> None:
    edital = _arquivo(1, "Edital")
    outros = _arquivo(2, "Outros Documentos")

    assert selecionar_documentos_principais([edital, outros]) == [edital]


def test_mapa_de_riscos_e_a_ultima_opcao() -> None:
    mapa_de_riscos = _arquivo(1, "Mapa de Riscos")
    minuta = _arquivo(2, "Minuta do Contrato")

    assert selecionar_documentos_principais([mapa_de_riscos, minuta]) == [minuta]


def test_tipo_desconhecido_e_analisado_em_vez_de_descartado() -> None:
    # O PNCP pode introduzir tipos novos; descartar o edital inteiro por não
    # reconhecer o rótulo é pior do que analisar o que existe.
    desconhecido = _arquivo(1, "Tipo Que Ainda Nao Existe")

    assert selecionar_documentos_principais([desconhecido]) == [desconhecido]


def test_sem_arquivo_nenhum_retorna_lista_vazia() -> None:
    assert selecionar_documentos_principais([]) == []


def test_inclui_todos_os_arquivos_do_mesmo_tipo_principal() -> None:
    edital_1 = _arquivo(1, "Edital")
    edital_2 = _arquivo(2, "Edital")
    tr = _arquivo(3, "Termo de Referência")

    assert selecionar_documentos_principais([edital_1, edital_2, tr]) == [
        edital_1,
        edital_2,
        tr,
    ]


def test_lista_arquivos_de_um_edital() -> None:
    def buscar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        return RespostaArquivos(
            status_code=200,
            corpo=[
                {
                    "sequencialDocumento": 1,
                    "titulo": "EDITAL-CRAS",
                    "tipoDocumentoNome": "Edital",
                    "url": "https://pncp.gov.br/.../arquivos/1",
                    "dataPublicacaoPncp": "2026-07-06T00:10:37",
                    "statusAtivo": True,
                },
                {
                    "sequencialDocumento": 2,
                    "titulo": "CRONOGRAMA",
                    "tipoDocumentoNome": "Outros Documentos",
                    "url": "https://pncp.gov.br/.../arquivos/2",
                    "dataPublicacaoPncp": "2026-07-06T00:10:39",
                    "statusAtivo": True,
                },
            ],
        )

    resultado = listar_arquivos(
        "88201298000149", 2026, 834, buscar, dormir=lambda s: None
    )

    assert resultado.erro is None
    assert resultado.arquivos == [
        ArquivoEdital(
            sequencial_documento=1,
            titulo="EDITAL-CRAS",
            tipo_documento_nome="Edital",
            url="https://pncp.gov.br/.../arquivos/1",
            data_publicacao_pncp="2026-07-06T00:10:37",
        ),
        ArquivoEdital(
            sequencial_documento=2,
            titulo="CRONOGRAMA",
            tipo_documento_nome="Outros Documentos",
            url="https://pncp.gov.br/.../arquivos/2",
            data_publicacao_pncp="2026-07-06T00:10:39",
        ),
    ]


def test_lista_vazia_quando_edital_nao_tem_arquivos() -> None:
    def buscar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        return RespostaArquivos(status_code=200, corpo=[])

    resultado = listar_arquivos("123", 2026, 1, buscar, dormir=lambda s: None)

    assert resultado.arquivos == []
    assert resultado.erro is None


def test_ignora_arquivos_inativos() -> None:
    def buscar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        return RespostaArquivos(
            status_code=200,
            corpo=[
                {
                    "sequencialDocumento": 1,
                    "titulo": "ATIVO",
                    "tipoDocumentoNome": "Edital",
                    "url": "u1",
                    "dataPublicacaoPncp": "2026-07-06T00:10:37",
                    "statusAtivo": True,
                },
                {
                    "sequencialDocumento": 2,
                    "titulo": "INATIVO",
                    "tipoDocumentoNome": "Edital",
                    "url": "u2",
                    "dataPublicacaoPncp": "2026-07-06T00:10:39",
                    "statusAtivo": False,
                },
            ],
        )

    resultado = listar_arquivos("123", 2026, 1, buscar, dormir=lambda s: None)

    assert [a.titulo for a in resultado.arquivos] == ["ATIVO"]


def test_lista_vazia_sem_erro_quando_pncp_responde_204() -> None:
    def buscar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        return RespostaArquivos(status_code=204, corpo=None)

    resultado = listar_arquivos("123", 2026, 1, buscar, dormir=lambda s: None)

    assert resultado.arquivos == []
    assert resultado.erro is None


def test_listar_tenta_de_novo_apos_limite_de_requisicoes_excedido() -> None:
    respostas = [
        RespostaArquivos(status_code=429, corpo=None),
        RespostaArquivos(
            status_code=200,
            corpo=[
                {
                    "sequencialDocumento": 1,
                    "titulo": "OK",
                    "tipoDocumentoNome": "Edital",
                    "url": "u1",
                    "dataPublicacaoPncp": "2026-07-06T00:10:37",
                    "statusAtivo": True,
                }
            ],
        ),
    ]

    def buscar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        return respostas.pop(0)

    esperas: list[float] = []
    resultado = listar_arquivos(
        "123", 2026, 1, buscar, dormir=esperas.append, aleatorio=lambda: 0.0
    )

    assert [a.titulo for a in resultado.arquivos] == ["OK"]
    assert resultado.erro is None
    assert esperas == [2.0]


def test_listar_soma_jitter_a_espera_do_backoff() -> None:
    # Com vários editais baixando em paralelo, um 429 costuma atingir várias
    # threads ao mesmo tempo: sem jitter todas dormem exatamente o mesmo tanto
    # e voltam a bater no PNCP juntas (thundering herd). O jitter é sorteado
    # dentro de [0, espera_base) e somado à espera exponencial.
    respostas = [
        RespostaArquivos(status_code=429, corpo=None),
        RespostaArquivos(status_code=429, corpo=None),
        RespostaArquivos(status_code=200, corpo=[]),
    ]

    def buscar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        return respostas.pop(0)

    esperas: list[float] = []
    listar_arquivos(
        "123",
        2026,
        1,
        buscar,
        dormir=esperas.append,
        aleatorio=lambda: 0.5,
    )

    # espera_base 2.0: tentativa 0 → 2.0 + 0.5*2.0, tentativa 1 → 4.0 + 0.5*2.0
    assert esperas == [3.0, 5.0]


def test_baixar_soma_jitter_a_espera_do_backoff() -> None:
    respostas = [
        RespostaDownload(status_code=503, conteudo=None),
        RespostaDownload(status_code=200, conteudo=b"ok", nome_arquivo="a.txt"),
    ]

    def baixar(url: str) -> RespostaDownload:
        return respostas.pop(0)

    esperas: list[float] = []
    baixar_arquivo("http://x/1", baixar, dormir=esperas.append, aleatorio=lambda: 1.0)

    assert esperas == [4.0]


def test_jitter_padrao_mantem_a_espera_dentro_da_janela_esperada() -> None:
    # Sem injetar `aleatorio`, o sorteio é real — a garantia observável é o
    # intervalo, não o valor: espera_exponencial <= espera < 2x espera_base.
    respostas = [
        RespostaDownload(status_code=503, conteudo=None),
        RespostaDownload(status_code=200, conteudo=b"ok", nome_arquivo="a.txt"),
    ]

    def baixar(url: str) -> RespostaDownload:
        return respostas.pop(0)

    esperas: list[float] = []
    baixar_arquivo("http://x/1", baixar, dormir=esperas.append)

    assert len(esperas) == 1
    assert 2.0 <= esperas[0] < 4.0


def test_listar_registra_erro_apos_falha_persistente() -> None:
    def buscar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        return RespostaArquivos(status_code=500, corpo=None)

    resultado = listar_arquivos(
        "123", 2026, 1, buscar, dormir=lambda s: None, max_tentativas=2
    )

    assert resultado.arquivos == []
    assert resultado.erro is not None
    assert "123" in resultado.erro


def test_baixa_conteudo_e_nome_de_um_arquivo() -> None:
    def baixar(url: str) -> RespostaDownload:
        return RespostaDownload(
            status_code=200, conteudo=b"conteudo do pdf", nome_arquivo="882797.pdf"
        )

    resultado = baixar_arquivo("http://x/1", baixar, dormir=lambda s: None)

    assert resultado == ArquivoBaixado(nome_arquivo="882797.pdf", conteudo=b"conteudo do pdf")


def test_baixa_tenta_de_novo_apos_erro_transitorio() -> None:
    respostas = [
        RespostaDownload(status_code=503, conteudo=None),
        RespostaDownload(status_code=200, conteudo=b"ok", nome_arquivo="a.txt"),
    ]

    def baixar(url: str) -> RespostaDownload:
        return respostas.pop(0)

    esperas: list[float] = []
    resultado = baixar_arquivo(
        "http://x/1", baixar, dormir=esperas.append, aleatorio=lambda: 0.0
    )

    assert resultado is not None
    assert resultado.conteudo == b"ok"
    assert esperas == [2.0]


def test_baixa_retorna_none_apos_falha_persistente() -> None:
    def baixar(url: str) -> RespostaDownload:
        return RespostaDownload(status_code=500, conteudo=None)

    resultado = baixar_arquivo(
        "http://x/1", baixar, dormir=lambda s: None, max_tentativas=2
    )

    assert resultado is None


def test_nome_seguro_mantem_nome_de_arquivo_normal() -> None:
    assert nome_de_arquivo_seguro("edital_89_2026_58_documento.pdf") == (
        "edital_89_2026_58_documento.pdf"
    )


def test_nome_seguro_extrai_basename_de_caminho_absoluto_url_encoded() -> None:
    # Achado real: alguns sistemas de origem (ex. atende.net) devolvem no
    # Content-Disposition o caminho absoluto do arquivo no *servidor deles*,
    # URL-encoded, em vez de só o nome do arquivo — usar isso cru como nome de
    # arquivo local tanto cria uma estrutura de diretórios que não existe
    # quanto (combinado ao prefixo do caminho local) estoura o limite de 260
    # caracteres do Windows, derrubando o download (visto na prática rodando
    # a Etapa 2 contra o top100_v4).
    bruto = (
        "%2Fvar%2Fwww%2Fhtml%2Fbrusque.atende.net%2Ftemp%2FWCO%2FPNCP%2FEdital"
        "%2Fedital_89_2026_58_documento.pdf"
    )
    assert nome_de_arquivo_seguro(bruto) == "edital_89_2026_58_documento.pdf"


def test_nome_seguro_extrai_basename_de_caminho_com_barra_normal() -> None:
    assert nome_de_arquivo_seguro("/var/www/html/edital.pdf") == "edital.pdf"


def test_nome_seguro_extrai_basename_de_caminho_com_contrabarra() -> None:
    assert nome_de_arquivo_seguro("C:\\temp\\edital.pdf") == "edital.pdf"


def test_nome_seguro_trunca_preservando_extensao() -> None:
    nome_longo = ("a" * 200) + ".pdf"

    resultado = nome_de_arquivo_seguro(nome_longo, maximo=80)

    assert len(resultado) <= 80
    assert resultado.endswith(".pdf")


def test_nome_seguro_trunca_sem_extensao_reconhecivel() -> None:
    nome_longo = "a" * 200

    resultado = nome_de_arquivo_seguro(nome_longo, maximo=80)

    assert resultado == "a" * 80


def test_nome_seguro_remove_caracteres_reservados_do_windows() -> None:
    # Achado do /code-review: unquote() pode revelar caracteres proibidos em
    # nome de arquivo no Windows (: * ? < > | ") que não são barra e por isso
    # não eram tratados pela extração de basename — um único ':' já derruba o
    # write_bytes com OSError, a mesma classe de falha que esta função existe
    # para evitar.
    assert nome_de_arquivo_seguro('relatório: final*.pdf') == "relatório_ final_.pdf"


def test_nome_seguro_trunca_sem_estourar_o_maximo_com_extensao_longa() -> None:
    # Achado do /code-review: com maximo pequeno em relação ao tamanho da
    # extensão, "espaco_para_raiz" ficava negativo e o slice `raiz[:-N]`
    # cortava do lado errado, devolvendo um nome MAIOR que o máximo pedido.
    resultado = nome_de_arquivo_seguro("documento.tarzarch", maximo=5)

    assert len(resultado) <= 5


def test_nome_seguro_usa_fallback_quando_nao_ha_basename() -> None:
    # Achado do /code-review: um Content-Disposition malformado que decodifica
    # só para a raiz ("/") não tem nenhum basename para extrair.
    assert nome_de_arquivo_seguro("%2F") == "arquivo"
