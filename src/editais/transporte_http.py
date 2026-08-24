from __future__ import annotations

import re
import threading

import requests
from requests.adapters import HTTPAdapter

from editais.coleta import ParametrosBusca, RespostaBusca
from editais.documentos import RespostaArquivos, RespostaDownload

URL_CONTRATACOES_PUBLICACAO = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
URL_ARQUIVOS_BASE = "https://pncp.gov.br/api/pncp/v1/orgaos"

# Tamanho do pool de conexões da sessão compartilhada. Sem sessão, cada
# requests.get abre conexão nova e paga handshake TLS — numa rodada real de
# 300 editais isso são ~1.000 handshakes contra o mesmo host. O padrão precisa
# acomodar o número de editais baixando em paralelo (ver
# chunks_de_editais.EDITAIS_SIMULTANEOS_PADRAO, hoje 4): com pool menor que a
# concorrência, urllib3 descarta conexão a cada uso e devolve o handshake que
# a sessão veio eliminar. Quem baixa em paralelo chama reiniciar_sessao() com
# o número exato de workers; este padrão serve aos chamadores seriais (coleta,
# scripts avulsos), que nunca passam de uma conexão em voo.
TAMANHO_POOL_PADRAO = 8

_sessao: requests.Session | None = None
_tamanho_pool = TAMANHO_POOL_PADRAO
# obter_sessao() é chamada de dentro dos workers de download: sem exclusão
# mútua, várias threads que chegam juntas na primeira chamada constroem cada
# uma a sua sessão e o pool compartilhado deixa de existir na prática.
_trava_sessao = threading.Lock()


def obter_sessao() -> requests.Session:
    global _sessao
    with _trava_sessao:
        if _sessao is None:
            _sessao = _criar_sessao(_tamanho_pool)
        return _sessao


def reiniciar_sessao(tamanho_pool: int = TAMANHO_POOL_PADRAO) -> None:
    """Descarta a sessão atual e passa a servir uma nova com este pool.

    Usado para dimensionar o pool ao teto de concorrência escolhido antes de
    disparar os downloads, e para isolar os testes entre si.

    **Precondição: chamar só com nenhum worker em voo.** A sessão anterior é
    fechada, e quem já tinha obtido a referência (obter_sessao() devolve e
    solta a trava) segue usando um objeto fechado. Não quebra — o urllib3
    reabre as conexões por baixo — mas devolve silenciosamente justamente os
    handshakes TLS que a sessão existe para eliminar. Na prática: chamar uma
    vez antes de abrir o ThreadPoolExecutor, nunca de dentro dele.
    """
    global _sessao, _tamanho_pool
    with _trava_sessao:
        if _sessao is not None:
            _sessao.close()
        _tamanho_pool = tamanho_pool
        _sessao = None


def _criar_sessao(tamanho_pool: int) -> requests.Session:
    sessao = requests.Session()
    adaptador = HTTPAdapter(pool_connections=tamanho_pool, pool_maxsize=tamanho_pool)
    sessao.mount("https://", adaptador)
    sessao.mount("http://", adaptador)
    return sessao


def buscar_via_http(params: ParametrosBusca) -> RespostaBusca:
    query: dict[str, str | int] = {
        "dataInicial": params.data_inicial,
        "dataFinal": params.data_final,
        "codigoModalidadeContratacao": params.codigo_modalidade_contratacao,
        "pagina": params.pagina,
        "tamanhoPagina": params.tamanho_pagina,
    }
    try:
        resposta = obter_sessao().get(URL_CONTRATACOES_PUBLICACAO, params=query, timeout=30)
    except requests.exceptions.RequestException:
        # Timeout / erro de conexão transitório do PNCP: reportado como 503 para
        # a camada de retry (coleta._buscar_com_retry) tratar com backoff.
        return RespostaBusca(status_code=503, corpo=None)
    corpo = resposta.json() if resposta.status_code == 200 else None
    return RespostaBusca(status_code=resposta.status_code, corpo=corpo)


def listar_arquivos_via_http(cnpj: str, ano: int, sequencial: int) -> RespostaArquivos:
    url = f"{URL_ARQUIVOS_BASE}/{cnpj}/compras/{ano}/{sequencial}/arquivos"
    try:
        resposta = obter_sessao().get(url, timeout=30)
    except requests.exceptions.RequestException:
        return RespostaArquivos(status_code=503, corpo=None)
    corpo = resposta.json() if resposta.status_code == 200 else None
    return RespostaArquivos(status_code=resposta.status_code, corpo=corpo)


def baixar_arquivo_via_http(url: str) -> RespostaDownload:
    try:
        resposta = obter_sessao().get(url, timeout=120)
    except requests.exceptions.RequestException:
        return RespostaDownload(status_code=503, conteudo=None)
    if resposta.status_code != 200:
        return RespostaDownload(status_code=resposta.status_code, conteudo=None)
    return RespostaDownload(
        status_code=200,
        conteudo=resposta.content,
        nome_arquivo=_nome_do_content_disposition(
            resposta.headers.get("Content-Disposition")
        ),
    )


def _nome_do_content_disposition(cabecalho: str | None) -> str | None:
    if not cabecalho:
        return None
    correspondencia = re.search(r'filename="?([^"]+)"?', cabecalho)
    return correspondencia.group(1) if correspondencia else None
