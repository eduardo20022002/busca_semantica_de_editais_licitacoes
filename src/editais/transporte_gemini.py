from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

import requests

from editais.triagem import Embedder
from editais.transporte_voyage import (
    _espera_ate_proximo_lote,
    _espera_do_retry,
    dividir_em_lotes,
)

URL_EMBEDDINGS_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MODELO_PADRAO = "gemini-embedding-001"

# SEMANTIC_SIMILARITY (não RETRIEVAL_DOCUMENT/RETRIEVAL_QUERY): o pipeline
# compara Chunks contra vetores do Perfil Aurora simetricamente (max pooling
# de cosseno nos dois sentidos), não faz busca assimétrica consulta->documento
# — é o mesmo motivo pelo qual a Voyage sempre usou input_type="document" nos
# dois lados. taskType é fixo (não parametrizado como o input_type da Voyage)
# porque não há um segundo uso legítimo no pipeline atual.
TASK_TYPE = "SEMANTIC_SIMILARITY"

# Free tier do gemini-embedding-001 (confirmado no fórum oficial do Google,
# ai.google.dev não publica a tabela): 100 RPM, 30.000 TPM, 1.000 RPD.
# Limite por requisição da própria API: até 250 textos OU 20.000 tokens,
# o que vier primeiro. Igual à Voyage (ADR-0001), ficamos deliberadamente
# abaixo do teto de TPM (aqui ~28.000, 80% de 30.000) porque a contagem local
# é estimada (~4 chars/token) e subestima texto real de edital.
TAMANHO_LOTE_PADRAO = 250
TOKENS_MAXIMOS_POR_LOTE_PADRAO = 14_000
SEGUNDOS_ENTRE_LOTES_PADRAO = 35.0
MAX_TENTATIVAS_PADRAO = 5
ESPERA_BASE_SEGUNDOS_PADRAO = 5.0
ESPERA_MAXIMA_SEGUNDOS_PADRAO = 60.0


def _carregar_dotenv(caminho: Path = Path(".env")) -> None:
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


def criar_embedder_gemini(
    *,
    modelo: str = MODELO_PADRAO,
    tamanho_lote: int = TAMANHO_LOTE_PADRAO,
    tokens_maximos_por_lote: int = TOKENS_MAXIMOS_POR_LOTE_PADRAO,
    segundos_entre_lotes: float = SEGUNDOS_ENTRE_LOTES_PADRAO,
    max_tentativas: int = MAX_TENTATIVAS_PADRAO,
    espera_base_segundos: float = ESPERA_BASE_SEGUNDOS_PADRAO,
    espera_maxima_segundos: float = ESPERA_MAXIMA_SEGUNDOS_PADRAO,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], float] = time.monotonic,
) -> Embedder:
    _carregar_dotenv()
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY não está definida no ambiente nem em .env.")

    # Mesmo motivo da Voyage (transporte_voyage.py): espaçamento por tempo de
    # parede, não só "entre lotes da mesma chamada" — vale mesmo quando o
    # embedder é chamado uma vez por edital.
    ultimo_lote_em: list[float | None] = [None]

    def embedder(textos: list[str]) -> list[list[float]]:
        lotes = dividir_em_lotes(
            textos,
            tamanho_maximo_lote=tamanho_lote,
            tokens_maximos_por_lote=tokens_maximos_por_lote,
        )
        vetores: list[list[float]] = []
        for lote in lotes:
            espera = _espera_ate_proximo_lote(
                ultimo_lote_em[0], relogio(), segundos_entre_lotes
            )
            if espera > 0:
                dormir(espera)
            ultimo_lote_em[0] = relogio()
            vetores.extend(
                _embeddar_lote(
                    lote, chave, modelo, max_tentativas, espera_base_segundos,
                    espera_maxima_segundos, dormir,
                )
            )
        return vetores

    return embedder


def _embeddar_lote(
    lote: list[str],
    chave: str,
    modelo: str,
    max_tentativas: int,
    espera_base_segundos: float,
    espera_maxima_segundos: float,
    dormir: Callable[[float], None],
) -> list[list[float]]:
    url = f"{URL_EMBEDDINGS_BASE}/{modelo}:batchEmbedContents"
    corpo = {
        "requests": [
            {
                "model": f"models/{modelo}",
                "content": {"parts": [{"text": texto}]},
                "taskType": TASK_TYPE,
            }
            for texto in lote
        ]
    }

    status_final = 0
    for tentativa in range(max_tentativas):
        try:
            resposta = requests.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": chave},
                json=corpo,
                timeout=60,
            )
        except requests.exceptions.RequestException:
            # Mesmo padrão de transporte_voyage.py/transporte_http.py: falha de
            # conexão acontece antes de haver status_code, trata como transitória.
            status_final = 503
            dormir(_espera_do_retry(tentativa, espera_base_segundos, espera_maxima_segundos))
            continue
        status_final = resposta.status_code
        if resposta.status_code == 200:
            # A ordem da resposta preserva a ordem da requisição (contrato da
            # API); diferente da Voyage, não há campo "index" para reordenar.
            return [item["values"] for item in resposta.json()["embeddings"]]
        if resposta.status_code == 429 or resposta.status_code >= 500:
            dormir(_espera_do_retry(tentativa, espera_base_segundos, espera_maxima_segundos))
            continue
        resposta.raise_for_status()
    raise RuntimeError(
        f"Falha ao embeddar lote após {max_tentativas} tentativas "
        f"(último status HTTP {status_final})."
    )
