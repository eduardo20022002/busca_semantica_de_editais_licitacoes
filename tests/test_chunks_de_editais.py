import json
import threading
import time
from pathlib import Path

from editais.chunks_de_editais import ProgressoDeEdital, obter_chunks_de_editais
from editais.documentos import RespostaArquivos, RespostaDownload


def _edital(numero: str, atualizacao: str = "2026-08-12T10:00:00") -> dict[str, object]:
    return {
        "numeroControlePNCP": numero,
        "orgaoEntidade": {"cnpj": "123"},
        "anoCompra": 2026,
        "sequencialCompra": 1,
        "dataAtualizacaoGlobal": atualizacao,
    }


def _listagem_de_um_edital(titulo: str = "EDITAL") -> RespostaArquivos:
    return RespostaArquivos(
        status_code=200,
        corpo=[
            {
                "sequencialDocumento": 1,
                "titulo": titulo,
                "tipoDocumentoNome": "Edital",
                "url": "http://x/1",
                "dataPublicacaoPncp": "2026-08-12T00:00:00",
                "statusAtivo": True,
            }
        ],
    )


def _texto_de_edital(objeto: str) -> bytes:
    # chunkar_texto janela textos longos; o conteúdo só precisa ser texto real
    # o bastante para produzir ao menos um Chunk.
    return (f"DO OBJETO\n{objeto}\n" + ("detalhamento do objeto contratado. " * 50)).encode(
        "utf-8"
    )


def test_processa_editais_em_paralelo(tmp_path: Path) -> None:
    # A razão de existir da mudança: com um edital por vez, a fase inteira fica
    # presa à latência de um download de cada vez.
    trava = threading.Lock()
    em_voo = 0
    pico_em_voo = 0

    def baixar(url: str) -> RespostaDownload:
        nonlocal em_voo, pico_em_voo
        with trava:
            em_voo += 1
            pico_em_voo = max(pico_em_voo, em_voo)
        time.sleep(0.05)  # segura o download em voo para forçar sobreposição real
        with trava:
            em_voo -= 1
        return RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("software"), nome_arquivo="e.txt"
        )

    numeros = [f"cnpj-1-{i:06d}/2026" for i in range(6)]
    resultado = obter_chunks_de_editais(
        numeros,
        {n: _edital(n) for n in numeros},
        diretorio_chunks=tmp_path / "chunks",
        diretorio_documentos=tmp_path / "documentos",
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=baixar,
        editais_simultaneos=4,
        dormir=lambda _: None,
    )

    assert len(resultado) == 6
    assert all(chunks for chunks in resultado.values())
    assert pico_em_voo > 1, "os editais rodaram em série, não em paralelo"


def test_resultado_preserva_a_ordem_de_entrada(tmp_path: Path) -> None:
    # Os editais terminam fora de ordem; o dicionário devolvido precisa sair na
    # ordem de Score de triagem que entrou, porque é ela que o corte top-N usa.
    numeros = [f"cnpj-1-{i:06d}/2026" for i in range(5)]
    atrasos = {n: 0.05 if i % 2 == 0 else 0.0 for i, n in enumerate(numeros)}
    urls_para_numero = {f"http://x/{n}": n for n in numeros}

    def listar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        numero = numeros[sequencial]
        return RespostaArquivos(
            status_code=200,
            corpo=[
                {
                    "sequencialDocumento": 1,
                    "titulo": "EDITAL",
                    "tipoDocumentoNome": "Edital",
                    "url": f"http://x/{numero}",
                    "dataPublicacaoPncp": "2026-08-12T00:00:00",
                    "statusAtivo": True,
                }
            ],
        )

    def baixar(url: str) -> RespostaDownload:
        time.sleep(atrasos[urls_para_numero[url]])
        return RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("x"), nome_arquivo="e.txt"
        )

    editais = {}
    for i, n in enumerate(numeros):
        edital = _edital(n)
        edital["sequencialCompra"] = i
        editais[n] = edital

    resultado = obter_chunks_de_editais(
        numeros,
        editais,
        diretorio_chunks=tmp_path / "chunks",
        diretorio_documentos=tmp_path / "documentos",
        listar=listar,
        baixar=baixar,
        editais_simultaneos=4,
        dormir=lambda _: None,
    )

    assert list(resultado.keys()) == numeros


def test_reaproveita_chunks_em_cache_sem_baixar(tmp_path: Path) -> None:
    # Idempotência entre execuções (Reprocessamento): um edital já processado e
    # não retificado não pode gastar rede de novo — é o que permite interromper
    # a fase no meio e retomar.
    diretorio_chunks = tmp_path / "chunks"
    diretorio_chunks.mkdir()
    (diretorio_chunks / "cnpj-1-000001_2026.json").write_text(
        json.dumps(
            {"dataAtualizacaoGlobal": "2026-08-12T10:00:00", "chunks": ["do cache"]}
        ),
        encoding="utf-8",
    )

    def baixar_que_falha_o_teste(url: str) -> RespostaDownload:
        raise AssertionError("baixou apesar de haver cache válido")

    resultado = obter_chunks_de_editais(
        ["cnpj-1-000001/2026"],
        {"cnpj-1-000001/2026": _edital("cnpj-1-000001/2026")},
        diretorio_chunks=diretorio_chunks,
        diretorio_documentos=tmp_path / "documentos",
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=baixar_que_falha_o_teste,
        editais_simultaneos=2,
        dormir=lambda _: None,
    )

    assert resultado == {"cnpj-1-000001/2026": ["do cache"]}


def test_edital_retificado_e_reprocessado(tmp_path: Path) -> None:
    diretorio_chunks = tmp_path / "chunks"
    diretorio_chunks.mkdir()
    (diretorio_chunks / "cnpj-1-000001_2026.json").write_text(
        json.dumps({"dataAtualizacaoGlobal": "2026-08-01T00:00:00", "chunks": ["velho"]}),
        encoding="utf-8",
    )

    resultado = obter_chunks_de_editais(
        ["cnpj-1-000001/2026"],
        {"cnpj-1-000001/2026": _edital("cnpj-1-000001/2026", "2026-08-12T10:00:00")},
        diretorio_chunks=diretorio_chunks,
        diretorio_documentos=tmp_path / "documentos",
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=lambda u: RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("novo"), nome_arquivo="e.txt"
        ),
        editais_simultaneos=2,
        dormir=lambda _: None,
    )

    assert resultado["cnpj-1-000001/2026"] != ["velho"]
    assert resultado["cnpj-1-000001/2026"], "o edital retificado deveria ter sido rebaixado"


def test_falha_em_um_edital_nao_derruba_os_outros(tmp_path: Path) -> None:
    # Política de "pular e registrar" (ADR-0007): em série, uma exceção só
    # perdia aquele edital; em paralelo, sem isolamento, ela sobe pelo executor
    # e mata a fase inteira — inclusive os editais já baixados e não gravados.
    numeros = ["ok-1-000001/2026", "explode-1-000002/2026", "ok-1-000003/2026"]

    def listar(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
        if cnpj == "explode":
            raise RuntimeError("erro inesperado de rede")
        return _listagem_de_um_edital()

    editais = {}
    for numero in numeros:
        edital = _edital(numero)
        edital["orgaoEntidade"] = {"cnpj": numero.split("-")[0]}
        editais[numero] = edital

    avisos: list[str] = []
    resultado = obter_chunks_de_editais(
        numeros,
        editais,
        diretorio_chunks=tmp_path / "chunks",
        diretorio_documentos=tmp_path / "documentos",
        listar=listar,
        baixar=lambda u: RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("x"), nome_arquivo="e.txt"
        ),
        editais_simultaneos=3,
        dormir=lambda _: None,
        registrar=avisos.append,
    )

    assert resultado["ok-1-000001/2026"], "edital saudável perdido por causa do vizinho"
    assert resultado["ok-1-000003/2026"], "edital saudável perdido por causa do vizinho"
    assert resultado["explode-1-000002/2026"] == []
    assert any("explode-1-000002/2026" in aviso for aviso in avisos)


def test_cache_corrompido_e_reprocessado_em_vez_de_virar_zero_chunks(
    tmp_path: Path,
) -> None:
    # Sem isto, um json truncado (interrupção no meio da gravação) fazia o
    # edital devolver [] chunks — e como a leitura falha igual na execução
    # seguinte, ele ficaria com Score de aderência zero PARA SEMPRE, sem nunca
    # se reparar. O cache ilegível tem que valer como "não há cache".
    diretorio_chunks = tmp_path / "chunks"
    diretorio_chunks.mkdir()
    (diretorio_chunks / "cnpj-1-000001_2026.json").write_text(
        '{"dataAtualizacaoGlobal": "2026-08-12T10:00:00", "chunks": ["trun',
        encoding="utf-8",
    )

    resultado = obter_chunks_de_editais(
        ["cnpj-1-000001/2026"],
        {"cnpj-1-000001/2026": _edital("cnpj-1-000001/2026")},
        diretorio_chunks=diretorio_chunks,
        diretorio_documentos=tmp_path / "documentos",
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=lambda u: RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("x"), nome_arquivo="e.txt"
        ),
        editais_simultaneos=2,
        dormir=lambda _: None,
    )

    assert resultado["cnpj-1-000001/2026"], "cache corrompido virou zero chunks"
    # e o arquivo precisa ter sido regravado, senão o problema volta amanhã
    cache = json.loads(
        (diretorio_chunks / "cnpj-1-000001_2026.json").read_text(encoding="utf-8")
    )
    assert cache["chunks"]


def test_callback_de_progresso_que_falha_nao_derruba_a_fase(tmp_path: Path) -> None:
    # O callback é código do chamador (imprime, escreve log). Se ele estoura
    # fora do try, a exceção sobe pelo executor e mata a fase inteira — o
    # mesmo desastre que o isolamento por edital existe para evitar.
    numeros = [f"cnpj-1-{i:06d}/2026" for i in range(4)]

    def callback_que_estoura(progresso: object) -> None:
        raise RuntimeError("log quebrou")

    resultado = obter_chunks_de_editais(
        numeros,
        {n: _edital(n) for n in numeros},
        diretorio_chunks=tmp_path / "chunks",
        diretorio_documentos=tmp_path / "documentos",
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=lambda u: RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("x"), nome_arquivo="e.txt"
        ),
        editais_simultaneos=2,
        dormir=lambda _: None,
        registrar=lambda _: None,
        ao_concluir=callback_que_estoura,
    )

    assert len(resultado) == 4
    assert all(chunks for chunks in resultado.values())


def test_paralelo_produz_o_mesmo_cache_que_o_serial(tmp_path: Path) -> None:
    # A garantia central da mudança: paralelizar não pode alterar o resultado,
    # só o tempo. Mesma entrada nos dois modos, mesmos arquivos de cache.
    numeros = [f"cnpj-1-{i:06d}/2026" for i in range(5)]
    editais = {n: _edital(n) for n in numeros}

    def rodar(diretorio: Path, simultaneos: int) -> dict[str, list[str]]:
        return obter_chunks_de_editais(
            numeros,
            editais,
            diretorio_chunks=diretorio / "chunks",
            diretorio_documentos=diretorio / "documentos",
            listar=lambda c, a, s: _listagem_de_um_edital(),
            baixar=lambda u: RespostaDownload(
                status_code=200, conteudo=_texto_de_edital("y"), nome_arquivo="e.txt"
            ),
            editais_simultaneos=simultaneos,
            dormir=lambda _: None,
        )

    em_serie = rodar(tmp_path / "serie", 1)
    em_paralelo = rodar(tmp_path / "paralelo", 4)

    assert em_serie == em_paralelo
    for numero in numeros:
        arquivo = f"{numero.replace('/', '_')}.json"
        assert (tmp_path / "serie" / "chunks" / arquivo).read_text(encoding="utf-8") == (
            tmp_path / "paralelo" / "chunks" / arquivo
        ).read_text(encoding="utf-8")


def test_baixa_todos_os_arquivos_mas_so_extrai_os_principais(tmp_path: Path) -> None:
    # ADR-0006: o download continua sendo de TODOS os arquivos ativos (cópia
    # para auditoria/arquivo); o filtro por tipo age só na extração. Sem este
    # teste, uma regressão que passasse a baixar só o Edital passaria batido.
    diretorio_documentos = tmp_path / "documentos"
    listagem = RespostaArquivos(
        status_code=200,
        corpo=[
            {
                "sequencialDocumento": 1,
                "titulo": "EDITAL",
                "tipoDocumentoNome": "Edital",
                "url": "http://x/principal",
                "dataPublicacaoPncp": "2026-08-12T00:00:00",
                "statusAtivo": True,
            },
            {
                "sequencialDocumento": 2,
                "titulo": "PLANILHA ORCAMENTARIA",
                "tipoDocumentoNome": "Outros Documentos",
                "url": "http://x/anexo",
                "dataPublicacaoPncp": "2026-08-12T00:00:00",
                "statusAtivo": True,
            },
        ],
    )
    conteudos = {
        "http://x/principal": _texto_de_edital("gestao hospitalar"),
        "http://x/anexo": _texto_de_edital("PALAVRA_SO_DO_ANEXO"),
    }
    baixados: list[str] = []

    def baixar(url: str) -> RespostaDownload:
        baixados.append(url)
        return RespostaDownload(
            status_code=200,
            conteudo=conteudos[url],
            nome_arquivo=url.rsplit("/", 1)[-1] + ".txt",
        )

    resultado = obter_chunks_de_editais(
        ["cnpj-1-000001/2026"],
        {"cnpj-1-000001/2026": _edital("cnpj-1-000001/2026")},
        diretorio_chunks=tmp_path / "chunks",
        diretorio_documentos=diretorio_documentos,
        listar=lambda c, a, s: listagem,
        baixar=baixar,
        editais_simultaneos=2,
        dormir=lambda _: None,
    )

    diretorio_edital = diretorio_documentos / "cnpj-1-000001_2026"
    assert sorted(baixados) == ["http://x/anexo", "http://x/principal"]
    assert (diretorio_edital / "1_principal.txt").exists()
    assert (diretorio_edital / "2_anexo.txt").exists(), "anexo deixou de ser arquivado"
    texto_chunkado = " ".join(resultado["cnpj-1-000001/2026"])
    assert "PALAVRA_SO_DO_ANEXO" not in texto_chunkado, "anexo entrou na análise"


def test_progresso_conta_editais_concluidos(tmp_path: Path) -> None:
    # Com vários editais em voo, a ordem de conclusão não é a de disparo — o
    # contador precisa refletir quantos terminaram, senão volta a parecer
    # travado numa execução longa (o problema que o log por edital resolveu).
    numeros = [f"cnpj-1-{i:06d}/2026" for i in range(5)]
    concluidos: list[int] = []
    trava = threading.Lock()

    def anotar(progresso: ProgressoDeEdital) -> None:
        with trava:
            concluidos.append(progresso.concluidos)

    obter_chunks_de_editais(
        numeros,
        {n: _edital(n) for n in numeros},
        diretorio_chunks=tmp_path / "chunks",
        diretorio_documentos=tmp_path / "documentos",
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=lambda u: RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("x"), nome_arquivo="e.txt"
        ),
        editais_simultaneos=4,
        dormir=lambda _: None,
        ao_concluir=anotar,
    )

    assert sorted(concluidos) == [1, 2, 3, 4, 5]


def test_persiste_chunks_e_documentos_em_disco(tmp_path: Path) -> None:
    diretorio_chunks = tmp_path / "chunks"
    diretorio_documentos = tmp_path / "documentos"

    obter_chunks_de_editais(
        ["cnpj-1-000001/2026"],
        {"cnpj-1-000001/2026": _edital("cnpj-1-000001/2026")},
        diretorio_chunks=diretorio_chunks,
        diretorio_documentos=diretorio_documentos,
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=lambda u: RespostaDownload(
            status_code=200, conteudo=_texto_de_edital("x"), nome_arquivo="edital.txt"
        ),
        editais_simultaneos=2,
        dormir=lambda _: None,
    )

    cache = json.loads(
        (diretorio_chunks / "cnpj-1-000001_2026.json").read_text(encoding="utf-8")
    )
    assert cache["dataAtualizacaoGlobal"] == "2026-08-12T10:00:00"
    assert cache["chunks"]
    assert (diretorio_documentos / "cnpj-1-000001_2026" / "1_edital.txt").exists()


def test_edital_ausente_da_listagem_do_dia_e_pulado(tmp_path: Path) -> None:
    # A triagem pode selecionar um número que não está no editais_*.json (a
    # coleta e a triagem são arquivos separados) — hoje isso é avisado e pulado.
    avisos: list[str] = []
    resultado = obter_chunks_de_editais(
        ["fantasma-1-000009/2026"],
        {},
        diretorio_chunks=tmp_path / "chunks",
        diretorio_documentos=tmp_path / "documentos",
        listar=lambda c, a, s: _listagem_de_um_edital(),
        baixar=lambda u: RespostaDownload(status_code=200, conteudo=b"x"),
        editais_simultaneos=2,
        dormir=lambda _: None,
        registrar=avisos.append,
    )

    assert resultado == {}
    assert any("fantasma-1-000009/2026" in aviso for aviso in avisos)
