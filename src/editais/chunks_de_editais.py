"""Obtenção dos Chunks dos Editais selecionados na triagem, em paralelo.

Por que existe: baixar os documentos era a fase mais lenta do pipeline diário
— medido em 2026-08-12, 1h36 de um total de 2h20 ponta a ponta (~70%), com 744
downloads em série. O custo não é CPU: extração de texto custa ~0,45s/MB e o
chunking é ~0,3% disso, então mesmo no limite superior (se TODOS os bytes
baixados fossem extraídos) o processamento local caberia em ~8 minutos. O
tempo era espera de rede, um edital de cada vez.

A unidade de paralelização é o Edital inteiro — listar, baixar todos os seus
arquivos, extrair, chunkar e persistir. É de propósito a mesma unidade do
cache em disco (`chunks/{slug}.json`) e da regra de Reprocessamento
(`precisa_reprocessar`): assim a idempotência entre execuções continua valendo
sem reprojetar o cache, e uma interrupção no meio da fase não deixa nenhum
edital pela metade.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from editais.analise_profunda import precisa_reprocessar
from editais.chunking import chunkar_texto
from editais.documentos import (
    BaixarArquivo,
    BuscarArquivos,
    baixar_arquivo,
    listar_arquivos,
    nome_de_arquivo_seguro,
    selecionar_documentos_principais,
)
from editais.extracao import extrair_textos_de_arquivo

# Quantos editais podem estar sendo baixados ao mesmo tempo.
#
# O PNCP não documenta rate limit, então este número veio de medição em vez de
# especificação (`scripts/medir_saturacao_pncp.py`, mesma amostra de 24
# arquivos reais em cada nível). Duas rodadas em 2026-08-13:
#
#   N     MB/s (1ª)   MB/s (2ª)   ganho sobre serial
#   1       1,07        1,18        1,00x
#   4       2,44        2,63        2,2-2,3x   <- adotado
#   8       2,27        1,70        1,4-2,1x
#  16       1,20        2,30        1,1-1,9x
#
# Duas conclusões, e a segunda é a que importa:
#
# 1. Nenhum 429/5xx em nível nenhum — o limite NÃO é rate limit. Aumentar a
#    concorrência não é "impolido" aqui, só é inútil.
# 2. A vazão satura em ~2,5 MB/s e não passa disso. Acima de N=4 as medições
#    não só param de crescer como divergem entre si (2,27 vs 1,70 em N=8) —
#    é ruído em torno de um teto, não uma curva de escala. Ou seja: o gargalo
#    remanescente é a banda contra o PNCP, não o número de conexões.
#
# 4 é o menor N que atinge o teto, então é o que dá o ganho sem manter conexão
# ociosa à toa. Ajustar só com medição nova em mãos, atualizando esta tabela.
EDITAIS_SIMULTANEOS_PADRAO = 4

@dataclass(frozen=True)
class ProgressoDeEdital:
    """Um Edital que acabou de ser processado, para o chamador reportar."""

    concluidos: int
    total: int
    numero: str
    chunks: int


ProgressoDeChunking = Callable[[ProgressoDeEdital], None]


def obter_chunks_de_editais(
    numeros: list[str],
    editais_por_numero: dict[str, dict[str, Any]],
    *,
    diretorio_chunks: Path,
    diretorio_documentos: Path,
    listar: BuscarArquivos,
    baixar: BaixarArquivo,
    editais_simultaneos: int = EDITAIS_SIMULTANEOS_PADRAO,
    dormir: Callable[[float], None] = time.sleep,
    registrar: Callable[[str], None] = print,
    ao_concluir: ProgressoDeChunking | None = None,
) -> dict[str, list[str]]:
    """Devolve os Chunks de cada Edital, na ordem em que `numeros` entrou.

    A ordem importa: `numeros` já vem ordenado por Score de triagem, e o corte
    top-N a jusante depende dela. Os editais terminam fora de ordem, então o
    dicionário é montado ao final a partir da lista original, não conforme
    cada worker devolve.
    """
    total = len(numeros)
    concluidos = [0]
    # `concluidos` é lido e incrementado por todos os workers; o executor não
    # serializa isso por nós.
    trava_progresso = threading.Lock()

    def processar(numero: str) -> list[str]:
        edital = editais_por_numero.get(numero)
        if edital is None:
            registrar(f"  [aviso] {numero} selecionado mas ausente da listagem do dia")
            return []
        try:
            return _obter_chunks_de_um_edital(
                numero,
                edital,
                diretorio_chunks=diretorio_chunks,
                diretorio_documentos=diretorio_documentos,
                listar=listar,
                baixar=baixar,
                dormir=dormir,
                registrar=registrar,
            )
        except Exception as erro:
            # Em série, uma exceção inesperada (erro de disco, formato
            # inesperado do PNCP) só custava aquele edital. Em paralelo ela
            # sobe pelo executor e mata a fase inteira, incluindo o trabalho
            # dos editais que já estavam baixados e ainda não persistidos —
            # daí o isolamento explícito, mesma política de "pular e registrar"
            # que extracao.py já aplica a arquivo ilegível.
            registrar(f"  [erro] {numero}: {type(erro).__name__}: {erro}")
            return []

    def processar_e_anotar(numero: str) -> list[str]:
        chunks = processar(numero)
        if ao_concluir is not None:
            with trava_progresso:
                concluidos[0] += 1
                posicao = concluidos[0]
            # Fora da trava: o callback é do chamador (imprime, escreve log) e
            # não deve serializar os workers entre si. Dentro do try pelo mesmo
            # motivo do isolamento acima — um log que estoura não pode custar
            # a fase inteira, e ele roda DEPOIS do trabalho de verdade.
            try:
                ao_concluir(ProgressoDeEdital(posicao, total, numero, len(chunks)))
            except Exception as erro:
                registrar(f"  [erro] progresso de {numero}: {type(erro).__name__}: {erro}")
        return chunks

    if editais_simultaneos <= 1 or total <= 1:
        resultados = [processar_e_anotar(numero) for numero in numeros]
    else:
        with ThreadPoolExecutor(max_workers=editais_simultaneos) as executor:
            resultados = list(executor.map(processar_e_anotar, numeros))

    return {
        numero: chunks
        for numero, chunks in zip(numeros, resultados)
        if numero in editais_por_numero
    }


def _obter_chunks_de_um_edital(
    numero: str,
    edital: dict[str, Any],
    *,
    diretorio_chunks: Path,
    diretorio_documentos: Path,
    listar: BuscarArquivos,
    baixar: BaixarArquivo,
    dormir: Callable[[float], None],
    registrar: Callable[[str], None],
) -> list[str]:
    data_atualizacao = edital.get("dataAtualizacaoGlobal", "")
    caminho_chunks = diretorio_chunks / f"{slug(numero)}.json"

    cache = _ler_chunks_cacheados(caminho_chunks)
    if cache is not None and not precisa_reprocessar(data_atualizacao, cache[0]):
        return cache[1]

    chunks = _baixar_e_chunkar(
        numero,
        edital,
        diretorio_documentos=diretorio_documentos,
        listar=listar,
        baixar=baixar,
        dormir=dormir,
        registrar=registrar,
    )
    _gravar_chunks(caminho_chunks, data_atualizacao, chunks)
    return chunks


def _baixar_e_chunkar(
    numero: str,
    edital: dict[str, Any],
    *,
    diretorio_documentos: Path,
    listar: BuscarArquivos,
    baixar: BaixarArquivo,
    dormir: Callable[[float], None],
    registrar: Callable[[str], None],
) -> list[str]:
    cnpj = edital["orgaoEntidade"]["cnpj"]
    ano = edital["anoCompra"]
    sequencial = edital["sequencialCompra"]

    resultado = listar_arquivos(cnpj, ano, sequencial, listar, dormir=dormir)
    if resultado.erro is not None:
        registrar(f"  [erro] {numero}: {resultado.erro}")
        return []

    diretorio_edital = diretorio_documentos / slug(numero)
    diretorio_edital.mkdir(parents=True, exist_ok=True)

    # Baixa todos os arquivos (auditoria/arquivo — ADR-0006), mas só extrai e
    # chunka o Edital principal + Termo de Referência (com fallback Projeto
    # Básico → ETP): anexos administrativos não descrevem o objeto contratado
    # e só inflam volume/custo de embedding sem sinal real.
    sequenciais_principais = {
        a.sequencial_documento for a in selecionar_documentos_principais(resultado.arquivos)
    }
    if not sequenciais_principais:
        registrar(f"  [aviso] {numero}: sem documento principal disponível (Edital/TR/PB/ETP)")

    textos: list[str] = []
    for arquivo in resultado.arquivos:
        baixado = baixar_arquivo(arquivo.url, baixar, dormir=dormir)
        if baixado is None:
            registrar(f"  [erro] {numero}: falha ao baixar '{arquivo.titulo}'")
            continue
        nome = baixado.nome_arquivo or arquivo.titulo
        nome_seguro = nome_de_arquivo_seguro(nome)
        (diretorio_edital / f"{arquivo.sequencial_documento}_{nome_seguro}").write_bytes(
            baixado.conteudo
        )
        if arquivo.sequencial_documento not in sequenciais_principais:
            continue
        extraidos = extrair_textos_de_arquivo(nome, baixado.conteudo)
        if not extraidos:
            registrar(f"  [pulado] {numero}: sem texto extraível de '{nome}'")
        textos.extend(t.texto for t in extraidos)

    return chunkar_texto("\n".join(textos))


def _ler_chunks_cacheados(caminho: Path) -> tuple[str, list[str]] | None:
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # Cache ilegível vale como "não há cache", e não como "zero chunks".
        # A diferença importa muito: tratado como erro, o edital devolveria []
        # e — como a leitura falharia igual na execução seguinte — ficaria com
        # Score de aderência zero para sempre, sem nunca se reparar sozinho.
        # Devolvendo None, ele é rebaixado e o arquivo é regravado.
        return None
    return dados.get("dataAtualizacaoGlobal", ""), dados.get("chunks", [])


def _gravar_chunks(caminho: Path, data_atualizacao: str, chunks: list[str]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(
        {"dataAtualizacaoGlobal": data_atualizacao, "chunks": chunks},
        ensure_ascii=False,
    )
    # Grava em temporário e troca por os.replace (atômico no mesmo volume, em
    # POSIX e Windows). Sem isso, uma interrupção no meio da gravação deixa
    # JSON truncado em disco — e o fluxo prático desta fase é justamente
    # interromper no meio (para rodar o pré-embedding) e retomar. A
    # concorrência agrava: passa de 1 arquivo em voo para EDITAIS_SIMULTANEOS.
    temporario = caminho.with_name(f"{caminho.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporario.write_text(conteudo, encoding="utf-8")
        os.replace(temporario, caminho)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise


def slug(texto: str) -> str:
    return texto.replace("/", "_").replace("\\", "_")
