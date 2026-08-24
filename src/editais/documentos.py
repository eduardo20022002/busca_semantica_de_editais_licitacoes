from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, TypeVar
from urllib.parse import unquote

MAXIMO_NOME_ARQUIVO_PADRAO = 80

# Caracteres proibidos em nome de arquivo no Windows (mesmo com o caminho
# dentro do limite de tamanho, um único ':' ou '*' no nome já derruba o
# write_bytes com OSError).
_CARACTERES_RESERVADOS_WINDOWS = re.compile(r'[<>:"|?*\x00-\x1f]')


def nome_de_arquivo_seguro(nome: str, maximo: int = MAXIMO_NOME_ARQUIVO_PADRAO) -> str:
    # Achado real: alguns sistemas de origem integrados ao PNCP (ex.
    # atende.net) devolvem no Content-Disposition o caminho absoluto do
    # arquivo no *servidor deles*, URL-encoded, em vez de só o nome do
    # arquivo — usar isso cru como nome de arquivo local tanto tenta criar uma
    # estrutura de diretórios que não existe quanto, combinado ao prefixo do
    # caminho local, estoura o limite de 260 caracteres do Windows.
    decodificado = unquote(nome).replace("\\", "/")
    base = PurePosixPath(decodificado).name or "arquivo"
    base = _CARACTERES_RESERVADOS_WINDOWS.sub("_", base)
    if len(base) <= maximo:
        return base
    raiz, ponto, extensao = base.rpartition(".")
    if ponto and 0 < len(extensao) <= 10 and len(extensao) + 1 <= maximo:
        espaco_para_raiz = maximo - len(extensao) - 1
        return f"{raiz[:espaco_para_raiz]}.{extensao}"
    return base[:maximo]


@dataclass(frozen=True)
class ArquivoEdital:
    sequencial_documento: int
    titulo: str
    tipo_documento_nome: str
    url: str
    data_publicacao_pncp: str


TIPO_EDITAL = "Edital"
# Ordem de prioridade do documento "Termo de Referência": usa o primeiro tipo
# desta cadeia que existir entre os arquivos do edital (fallback).
TIPOS_TERMO_REFERENCIA_EM_ORDEM = (
    "Termo de Referência",
    "Projeto Básico",
    "Estudo Técnico Preliminar",
)

# Última instância, usada só quando o edital não publica NENHUM dos tipos
# canônicos acima. Nem todo órgão classifica os arquivos corretamente no PNCP:
# numa amostra de 100 editais, "Outros Documentos" (106 arquivos) apareceu quase
# tanto quanto "Edital" (112), e 7 editais não tinham Edital nem TR — em vários
# deles o edital real estava lá dentro, com mais de 150 mil caracteres de texto.
# Sem esta cadeia esses editais entram na Análise profunda com zero Chunk, ou
# seja, são silenciosamente descartados do funil.
#
# A ordem vai do mais para o menos descritivo do objeto contratado; o Mapa de
# Riscos fica por último porque descreve o risco do certame, não o que se compra.
TIPOS_ULTIMA_INSTANCIA_EM_ORDEM = (
    "DFD",
    "Minuta do Contrato",
    "Minuta de Ata de Registro de Preços",
    "Outros Documentos",
    "Mapa de Riscos",
)


def selecionar_documentos_principais(arquivos: list[ArquivoEdital]) -> list[ArquivoEdital]:
    editais = _filtrar_por_tipo(arquivos, TIPO_EDITAL)
    termo_de_referencia = _primeiro_tipo_disponivel(arquivos, TIPOS_TERMO_REFERENCIA_EM_ORDEM)

    principais = editais + termo_de_referencia
    if principais:
        return principais

    ultima_instancia = _primeiro_tipo_disponivel(arquivos, TIPOS_ULTIMA_INSTANCIA_EM_ORDEM)
    if ultima_instancia:
        return ultima_instancia

    # Tipo fora de qualquer cadeia conhecida (o PNCP pode introduzir tipos
    # novos): melhor analisar o que existe do que descartar o edital inteiro.
    return list(arquivos)


def _primeiro_tipo_disponivel(
    arquivos: list[ArquivoEdital], tipos_em_ordem: tuple[str, ...]
) -> list[ArquivoEdital]:
    for tipo in tipos_em_ordem:
        candidatos = _filtrar_por_tipo(arquivos, tipo)
        if candidatos:
            return candidatos
    return []


def _filtrar_por_tipo(arquivos: list[ArquivoEdital], tipo: str) -> list[ArquivoEdital]:
    return [a for a in arquivos if a.tipo_documento_nome == tipo]


@dataclass(frozen=True)
class RespostaArquivos:
    status_code: int
    corpo: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class RespostaDownload:
    status_code: int
    conteudo: bytes | None = None
    # Nome real do arquivo (com extensão), lido do cabeçalho Content-Disposition
    # da resposta — o `titulo` da listagem não traz extensão, e a extração
    # despacha justamente por extensão.
    nome_arquivo: str | None = None


@dataclass(frozen=True)
class ArquivoBaixado:
    nome_arquivo: str | None
    conteudo: bytes


BuscarArquivos = Callable[[str, int, int], RespostaArquivos]
BaixarArquivo = Callable[[str], RespostaDownload]


@dataclass(frozen=True)
class ResultadoArquivos:
    arquivos: list[ArquivoEdital]
    erro: str | None


MAX_TENTATIVAS_PADRAO = 5
ESPERA_BASE_SEGUNDOS_PADRAO = 2.0

_Resposta = TypeVar("_Resposta")


def _obter_com_retry(
    chamar: Callable[[], _Resposta],
    status_de: Callable[[_Resposta], int],
    dormir: Callable[[float], None],
    max_tentativas: int,
    espera_base_segundos: float,
    aleatorio: Callable[[], float],
) -> _Resposta | None:
    # Mesma política de backoff de coleta._buscar_com_retry: repete em 429/5xx
    # (transitórios) com espera exponencial; devolve a resposta no primeiro
    # status terminal (o chamador a interpreta), ou None se esgotar as tentativas.
    #
    # O jitter existe por causa da concorrência: com vários editais baixando ao
    # mesmo tempo, um 429 do PNCP costuma atingir várias threads na mesma
    # janela. Espera puramente exponencial faz todas acordarem juntas e
    # baterem juntas de novo (thundering herd) — o backoff vira sincronizador
    # em vez de amortecedor. Sorteado em [0, espera_base) e somado, para que a
    # espera nunca fique MENOR que a exponencial que já era praticada.
    for tentativa in range(max_tentativas):
        resposta = chamar()
        status = status_de(resposta)
        if status == 429 or status >= 500:
            exponencial = espera_base_segundos * (2**tentativa)
            dormir(exponencial + aleatorio() * espera_base_segundos)
            continue
        return resposta
    return None


def listar_arquivos(
    cnpj: str,
    ano: int,
    sequencial: int,
    buscar: BuscarArquivos,
    *,
    dormir: Callable[[float], None],
    max_tentativas: int = MAX_TENTATIVAS_PADRAO,
    espera_base_segundos: float = ESPERA_BASE_SEGUNDOS_PADRAO,
    aleatorio: Callable[[], float] = random.random,
) -> ResultadoArquivos:
    resposta = _obter_com_retry(
        lambda: buscar(cnpj, ano, sequencial),
        lambda r: r.status_code,
        dormir,
        max_tentativas,
        espera_base_segundos,
        aleatorio,
    )
    erro = ResultadoArquivos(
        arquivos=[],
        erro=f"falha ao listar arquivos do edital {cnpj}/{ano}/{sequencial}",
    )
    if resposta is None:
        return erro
    # 204 (No Content) é a resposta do PNCP para um edital sem arquivos
    # anexados — é ausência de documentos, não erro.
    if resposta.status_code == 204:
        return ResultadoArquivos(arquivos=[], erro=None)
    if resposta.status_code != 200:
        return erro
    arquivos = [
        ArquivoEdital(
            sequencial_documento=item["sequencialDocumento"],
            titulo=item["titulo"],
            tipo_documento_nome=item["tipoDocumentoNome"],
            url=item["url"],
            data_publicacao_pncp=item["dataPublicacaoPncp"],
        )
        for item in (resposta.corpo or [])
        if item.get("statusAtivo", True)
    ]
    return ResultadoArquivos(arquivos=arquivos, erro=None)


def baixar_arquivo(
    url: str,
    baixar: BaixarArquivo,
    *,
    dormir: Callable[[float], None],
    max_tentativas: int = MAX_TENTATIVAS_PADRAO,
    espera_base_segundos: float = ESPERA_BASE_SEGUNDOS_PADRAO,
    aleatorio: Callable[[], float] = random.random,
) -> ArquivoBaixado | None:
    resposta = _obter_com_retry(
        lambda: baixar(url),
        lambda r: r.status_code,
        dormir,
        max_tentativas,
        espera_base_segundos,
        aleatorio,
    )
    if resposta is not None and resposta.status_code == 200 and resposta.conteudo is not None:
        return ArquivoBaixado(nome_arquivo=resposta.nome_arquivo, conteudo=resposta.conteudo)
    return None
