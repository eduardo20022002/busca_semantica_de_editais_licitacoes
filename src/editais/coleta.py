from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ParametrosBusca:
    data_inicial: str
    data_final: str
    codigo_modalidade_contratacao: int
    pagina: int
    tamanho_pagina: int


@dataclass(frozen=True)
class RespostaBusca:
    status_code: int
    corpo: dict[str, Any] | None = None


BuscarContratacoes = Callable[[ParametrosBusca], RespostaBusca]


@dataclass(frozen=True)
class ErroPagina:
    modalidade: int
    pagina: int
    motivo: str


@dataclass(frozen=True)
class ResultadoColeta:
    editais: list[dict[str, Any]]
    erros: list[ErroPagina]


MAX_TENTATIVAS_PADRAO = 5
ESPERA_BASE_SEGUNDOS_PADRAO = 2.0
INTERVALO_MINIMO_SEGUNDOS_PADRAO = 1.0


def coletar_editais(
    data_inicial: str,
    data_final: str,
    modalidades: list[int],
    buscar: BuscarContratacoes,
    *,
    dormir: Callable[[float], None],
    max_tentativas: int = MAX_TENTATIVAS_PADRAO,
    espera_base_segundos: float = ESPERA_BASE_SEGUNDOS_PADRAO,
    intervalo_minimo_segundos: float = INTERVALO_MINIMO_SEGUNDOS_PADRAO,
) -> ResultadoColeta:
    editais: list[dict[str, Any]] = []
    erros: list[ErroPagina] = []
    primeira_requisicao = True

    for modalidade in modalidades:
        pagina = 1
        total_paginas = 1
        while pagina <= total_paginas:
            if primeira_requisicao:
                primeira_requisicao = False
            else:
                dormir(intervalo_minimo_segundos)

            params = ParametrosBusca(
                data_inicial=data_inicial,
                data_final=data_final,
                codigo_modalidade_contratacao=modalidade,
                pagina=pagina,
                tamanho_pagina=50,
            )
            resposta = _buscar_com_retry(
                buscar, params, max_tentativas, espera_base_segundos, dormir
            )
            if resposta is None:
                erros.append(
                    ErroPagina(
                        modalidade=modalidade,
                        pagina=pagina,
                        motivo="limite de requisições excedido após retries",
                    )
                )
            else:
                corpo = resposta.corpo or {}
                editais.extend(corpo.get("data", []))
                total_paginas = corpo.get("totalPaginas", total_paginas)
            pagina += 1

    return ResultadoColeta(editais=editais, erros=erros)


def _buscar_com_retry(
    buscar: BuscarContratacoes,
    params: ParametrosBusca,
    max_tentativas: int,
    espera_base_segundos: float,
    dormir: Callable[[float], None],
) -> RespostaBusca | None:
    for tentativa in range(max_tentativas):
        resposta = buscar(params)
        if resposta.status_code == 200:
            return resposta
        if resposta.status_code == 429 or resposta.status_code >= 500:
            dormir(espera_base_segundos * (2**tentativa))
            continue
        return None
    return None
