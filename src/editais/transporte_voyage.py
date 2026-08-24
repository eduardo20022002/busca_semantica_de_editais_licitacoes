from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import requests

from editais.triagem import Embedder

URL_EMBEDDINGS = "https://api.voyageai.com/v1/embeddings"
# Score de triagem (alto volume) usa o lite; a Análise profunda (volume menor,
# resultado vira o Score de aderência visto pelo analista) usa voyage-4, de
# melhor qualidade — ambos gratuitos na série 4 (ADR-0001).
MODELO_PADRAO = "voyage-4-lite"
MODELO_ANALISE_PROFUNDA = "voyage-4"
# Cartão cadastrado em 2026-08-05 (ADR-0001): saiu do tier sem pagamento
# (3 RPM / 10K TPM) para o Tier 1 (2.000 RPM / 8M TPM no voyage-4 — o mais
# apertado dos dois modelos da série 4 em uso; voyage-4-lite tem 1M tokens/
# requisição contra 320K do voyage-4, então dimensionamos pelo voyage-4 e o
# lite fica com folga de sobra). O teto por REQUISIÇÃO (não por minuto) da
# própria Voyage é o que limita o tamanho do lote: até 1.000 textos e até
# 320K tokens (voyage-4) por chamada.
#
# 200K tokens ESTIMADOS (a margem original, ~62% do teto de 320K) bateu em
# HTTP 400 "TOO_MANY_TOKENS_IN_BATCH" na prática: um lote de chunks legítimos
# (~2000 chars cada, texto jurídico em português) tinha 200.000 tokens pela
# nossa estimativa (~4 chars/token) mas **521.106 tokens reais** pelo
# tokenizer da Voyage — 2,61x subestimado, não os ~1,6x de margem que a conta
# original assumia. 90K tokens estimados dá margem até um fator ~3,5x antes de
# reencontrar o teto de 320K — folga real sobre o que já foi medido, não só
# sobre a suposição de ~4 chars/token (que segue sem validação melhor).
# 5s de espaçamento entre lotes usa ~1M TPM mesmo já corrigindo pelo fator
# 2,61x medido (13% do teto de 8M) — folgado de propósito, porque a latência
# real de uma requisição grande já deve dominar o intervalo na prática.
TAMANHO_LOTE_PADRAO = 1_000
TOKENS_MAXIMOS_POR_LOTE_PADRAO = 90_000
SEGUNDOS_ENTRE_LOTES_PADRAO = 5.0

# Quantos lotes podem estar em voo ao mesmo tempo. O padrão 1 mantém o
# comportamento estritamente sequencial de sempre — concorrência é opt-in.
#
# Medição (2026-08-11): com 1 lote por vez, cada requisição de ~235K tokens
# reais levava ~28s, então o espaçamento de 5s nunca era o limitante — a
# latência era. Sequencial, isso dá ~2 req/min contra o teto de 2.000 RPM do
# Tier 1: a vazão estava presa na latência de UMA requisição, não no limite
# da conta. Vários lotes em voo atacam exatamente isso.
LOTES_SIMULTANEOS_PADRAO = 1
MAX_TENTATIVAS_PADRAO = 5
ESPERA_BASE_SEGUNDOS_PADRAO = 5.0
# Teto do backoff exponencial: sem isso, espera_base_segundos * 2**tentativa
# cresce sem limite — com parâmetros mais pacientes (ex. mais tentativas para
# tolerar rate limit) uma única tentativa pode acabar esperando horas em vez de
# minutos. 60s é generoso o bastante para o rate limit da Voyage limpar.
ESPERA_MAXIMA_SEGUNDOS_PADRAO = 60.0


def _estimar_tokens(texto: str) -> int:
    # Aproximação conservadora (sem tokenizer da Voyage disponível localmente):
    # ~4 caracteres por token é uma estimativa comum para textos latinos.
    return max(1, len(texto) // 4)


def dividir_em_lotes(
    textos: list[str],
    *,
    tamanho_maximo_lote: int,
    tokens_maximos_por_lote: int,
    estimar_tokens: Callable[[str], int] = _estimar_tokens,
) -> list[list[str]]:
    lotes: list[list[str]] = []
    lote_atual: list[str] = []
    tokens_no_lote_atual = 0

    for texto in textos:
        tokens_do_texto = estimar_tokens(texto)
        excede_tamanho = len(lote_atual) >= tamanho_maximo_lote
        excede_tokens = (
            lote_atual and tokens_no_lote_atual + tokens_do_texto > tokens_maximos_por_lote
        )
        if excede_tamanho or excede_tokens:
            lotes.append(lote_atual)
            lote_atual = []
            tokens_no_lote_atual = 0

        lote_atual.append(texto)
        tokens_no_lote_atual += tokens_do_texto

    if lote_atual:
        lotes.append(lote_atual)

    return lotes


def _carregar_dotenv(caminho: Path = Path(".env")) -> None:
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


def criar_embedder_voyage(
    *,
    modelo: str = MODELO_PADRAO,
    input_type: str = "document",
    tamanho_lote: int = TAMANHO_LOTE_PADRAO,
    tokens_maximos_por_lote: int = TOKENS_MAXIMOS_POR_LOTE_PADRAO,
    segundos_entre_lotes: float = SEGUNDOS_ENTRE_LOTES_PADRAO,
    lotes_simultaneos: int = LOTES_SIMULTANEOS_PADRAO,
    max_tentativas: int = MAX_TENTATIVAS_PADRAO,
    espera_base_segundos: float = ESPERA_BASE_SEGUNDOS_PADRAO,
    espera_maxima_segundos: float = ESPERA_MAXIMA_SEGUNDOS_PADRAO,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], float] = time.monotonic,
) -> Embedder:
    _carregar_dotenv()
    chave = os.environ.get("VOYAGE_API_KEY")
    if not chave:
        raise RuntimeError(
            "VOYAGE_API_KEY não está definida no ambiente nem em .env."
        )

    # Espaçamento por tempo de parede (não "só entre lotes da mesma chamada"): o
    # intervalo mínimo entre requisições vale mesmo quando o embedder é chamado
    # uma vez por edital (Análise profunda) — senão o fim de um edital e o começo
    # do próximo saem coladas e estouram o rate limit.
    ultimo_lote_em: list[float | None] = [None]
    # Com vários lotes em voo, decidir "posso disparar agora?" deixa de ser
    # seguro sem exclusão mútua: duas threads leriam o mesmo último-início e
    # sairiam juntas, furando o espaçamento. A reserva do horário acontece sob
    # a trava; a espera em si, fora dela.
    trava_espacamento = threading.Lock()

    def _aguardar_a_vez() -> None:
        with trava_espacamento:
            agora = relogio()
            espera = _espera_ate_proximo_lote(
                ultimo_lote_em[0], agora, segundos_entre_lotes
            )
            ultimo_lote_em[0] = agora + espera
        if espera > 0:
            dormir(espera)

    def _processar_lote(lote: list[str]) -> list[list[float]]:
        _aguardar_a_vez()
        return _embeddar_lote(
            lote,
            chave,
            modelo,
            input_type,
            max_tentativas,
            espera_base_segundos,
            espera_maxima_segundos,
            dormir,
        )

    def embedder(textos: list[str]) -> list[list[float]]:
        lotes = dividir_em_lotes(
            textos,
            tamanho_maximo_lote=tamanho_lote,
            tokens_maximos_por_lote=tokens_maximos_por_lote,
        )
        if lotes_simultaneos <= 1 or len(lotes) <= 1:
            return [vetor for lote in lotes for vetor in _processar_lote(lote)]

        # executor.map preserva a ordem dos resultados, então os vetores saem
        # alinhados com os textos de entrada mesmo com os lotes terminando
        # fora de ordem.
        with ThreadPoolExecutor(max_workers=lotes_simultaneos) as executor:
            resultados = list(executor.map(_processar_lote, lotes))
        return [vetor for resultado in resultados for vetor in resultado]

    return embedder


def _espera_ate_proximo_lote(
    ultimo_lote_em: float | None, agora: float, segundos_entre_lotes: float
) -> float:
    if ultimo_lote_em is None:
        return 0.0
    return max(0.0, segundos_entre_lotes - (agora - ultimo_lote_em))


def _espera_do_retry(tentativa: int, espera_base_segundos: float, espera_maxima_segundos: float) -> float:
    # Sem teto, espera_base_segundos * 2**tentativa cresce sem limite — com
    # parâmetros mais pacientes (mais tentativas, base maior) uma única
    # tentativa pode acabar esperando horas em vez de minutos.
    return min(espera_base_segundos * (2**tentativa), espera_maxima_segundos)


def _excesso_de_tokens(resposta: requests.Response) -> bool:
    try:
        corpo = resposta.json()
    except ValueError:
        return False
    return isinstance(corpo, dict) and corpo.get("error_code") == "TOO_MANY_TOKENS_IN_BATCH"


def _embeddar_lote(
    lote: list[str],
    chave: str,
    modelo: str,
    input_type: str,
    max_tentativas: int,
    espera_base_segundos: float,
    espera_maxima_segundos: float,
    dormir: Callable[[float], None],
) -> list[list[float]]:
    status_final = 0
    for tentativa in range(max_tentativas):
        try:
            resposta = requests.post(
                URL_EMBEDDINGS,
                headers={"Authorization": f"Bearer {chave}"},
                json={"input": lote, "model": modelo, "input_type": input_type},
                timeout=60,
            )
        except requests.exceptions.RequestException:
            # Falha de conexão (ex. "Broken pipe") acontece antes de haver uma
            # resposta com status_code — trata como transitória, mesmo padrão
            # já usado em transporte_http.py.
            status_final = 503
            dormir(_espera_do_retry(tentativa, espera_base_segundos, espera_maxima_segundos))
            continue
        status_final = resposta.status_code
        if resposta.status_code == 200:
            dados = resposta.json()["data"]
            ordenados = sorted(dados, key=lambda registro: registro["index"])
            return [registro["embedding"] for registro in ordenados]
        if resposta.status_code == 429 or resposta.status_code >= 500:
            dormir(_espera_do_retry(tentativa, espera_base_segundos, espera_maxima_segundos))
            continue
        if resposta.status_code == 400 and len(lote) > 1 and _excesso_de_tokens(resposta):
            # Achado real: a razão tokens-reais/tokens-estimados NÃO é
            # constante mesmo dentro do mesmo edital (medida em 2,61x e 3,86x
            # em lotes de tamanho idêntico) — nenhuma margem estática sobre a
            # estimativa por caractere é confiável para conteúdo assim. Em vez
            # de adivinhar melhor, reage ao erro real: divide o lote pela
            # metade e tenta cada metade separadamente, recursivamente até
            # caber sob o teto de tokens por requisição da própria Voyage.
            meio = len(lote) // 2
            primeira = _embeddar_lote(
                lote[:meio], chave, modelo, input_type, max_tentativas,
                espera_base_segundos, espera_maxima_segundos, dormir,
            )
            segunda = _embeddar_lote(
                lote[meio:], chave, modelo, input_type, max_tentativas,
                espera_base_segundos, espera_maxima_segundos, dormir,
            )
            return primeira + segunda
        # Erro terminal (não é rate limit, falha transitória do servidor, nem
        # excesso de tokens) — não adianta tentar de novo. O corpo da resposta
        # é onde a Voyage explica o motivo; raise_for_status() descarta isso e
        # obriga a reproduzir manualmente para descobrir por quê. Erro real
        # que já custou uma investigação, deixado aqui visível.
        raise RuntimeError(
            f"Voyage retornou HTTP {resposta.status_code} para um lote de "
            f"{len(lote)} textos: {resposta.text[:500]}"
        )
    raise RuntimeError(
        f"Falha ao embeddar lote após {max_tentativas} tentativas "
        f"(último status HTTP {status_final})."
    )
