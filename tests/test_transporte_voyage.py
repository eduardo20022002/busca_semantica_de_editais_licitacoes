import threading
import time

import pytest

from editais.transporte_voyage import (
    _espera_ate_proximo_lote,
    _espera_do_retry,
    _excesso_de_tokens,
    dividir_em_lotes,
)


class _RespostaFalsa:
    """Duplo de teste de requests.Response: só o que _excesso_de_tokens usa."""

    def __init__(self, corpo: object, valida: bool = True) -> None:
        self._corpo = corpo
        self._valida = valida

    def json(self) -> object:
        if not self._valida:
            raise ValueError("corpo não é JSON válido")
        return self._corpo


def test_excesso_de_tokens_reconhece_o_error_code_da_voyage() -> None:
    resposta = _RespostaFalsa({"error_code": "TOO_MANY_TOKENS_IN_BATCH", "detail": "..."})
    assert _excesso_de_tokens(resposta) is True  # type: ignore[arg-type]


def test_excesso_de_tokens_falso_para_outro_error_code() -> None:
    resposta = _RespostaFalsa({"error_code": "INVALID_API_KEY"})
    assert _excesso_de_tokens(resposta) is False  # type: ignore[arg-type]


def test_excesso_de_tokens_falso_quando_corpo_nao_e_json() -> None:
    resposta = _RespostaFalsa(None, valida=False)
    assert _excesso_de_tokens(resposta) is False  # type: ignore[arg-type]


def test_excesso_de_tokens_falso_quando_corpo_nao_e_dict() -> None:
    resposta = _RespostaFalsa(["lista", "nao", "dict"])
    assert _excesso_de_tokens(resposta) is False  # type: ignore[arg-type]


def test_espera_do_retry_cresce_exponencialmente_antes_do_teto() -> None:
    assert _espera_do_retry(0, espera_base_segundos=5.0, espera_maxima_segundos=60.0) == 5.0
    assert _espera_do_retry(1, espera_base_segundos=5.0, espera_maxima_segundos=60.0) == 10.0
    assert _espera_do_retry(2, espera_base_segundos=5.0, espera_maxima_segundos=60.0) == 20.0


def test_espera_do_retry_nao_ultrapassa_o_teto() -> None:
    # base=25, tentativa=9 daria 25*512=12800s sem teto; com teto de 60s, fica 60
    assert _espera_do_retry(9, espera_base_segundos=25.0, espera_maxima_segundos=60.0) == 60.0


def test_primeiro_lote_nao_espera() -> None:
    assert _espera_ate_proximo_lote(None, agora=100.0, segundos_entre_lotes=50.0) == 0.0


def test_espera_o_intervalo_restante_desde_o_ultimo_lote() -> None:
    # último lote foi em t=100; agora é t=120; intervalo mínimo 50 -> falta 30
    assert _espera_ate_proximo_lote(100.0, agora=120.0, segundos_entre_lotes=50.0) == 30.0


def test_nao_espera_quando_o_intervalo_ja_passou() -> None:
    # entre chamadas separadas (um edital e o próximo), se já passou o intervalo
    # não dorme de novo
    assert _espera_ate_proximo_lote(100.0, agora=160.0, segundos_entre_lotes=50.0) == 0.0


def _tokens_por_palavra(texto: str) -> int:
    return len(texto.split())


def test_divide_por_orcamento_de_tokens_quando_excede_o_limite() -> None:
    textos = ["um dois tres", "quatro cinco seis", "sete oito nove"]

    lotes = dividir_em_lotes(
        textos,
        tamanho_maximo_lote=10,
        tokens_maximos_por_lote=5,
        estimar_tokens=_tokens_por_palavra,
    )

    assert lotes == [["um dois tres"], ["quatro cinco seis"], ["sete oito nove"]]


def test_agrupa_varios_textos_pequenos_no_mesmo_lote_quando_cabe() -> None:
    textos = ["a", "b", "c", "d"]

    lotes = dividir_em_lotes(
        textos,
        tamanho_maximo_lote=10,
        tokens_maximos_por_lote=100,
        estimar_tokens=_tokens_por_palavra,
    )

    assert lotes == [["a", "b", "c", "d"]]


def test_respeita_tamanho_maximo_do_lote_mesmo_com_orcamento_de_tokens_de_sobra() -> None:
    textos = ["a", "b", "c", "d", "e"]

    lotes = dividir_em_lotes(
        textos,
        tamanho_maximo_lote=2,
        tokens_maximos_por_lote=1000,
        estimar_tokens=_tokens_por_palavra,
    )

    assert lotes == [["a", "b"], ["c", "d"], ["e"]]


def test_texto_sozinho_maior_que_o_orcamento_forma_lote_proprio() -> None:
    textos = ["um dois tres quatro cinco seis sete", "curto"]

    lotes = dividir_em_lotes(
        textos,
        tamanho_maximo_lote=10,
        tokens_maximos_por_lote=3,
        estimar_tokens=_tokens_por_palavra,
    )

    assert lotes == [["um dois tres quatro cinco seis sete"], ["curto"]]


def test_embedder_concorrente_preserva_a_ordem_e_de_fato_paraleliza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Com lotes em voo simultâneos, os lotes terminam fora de ordem — os
    # vetores ainda precisam sair alinhados com os textos de entrada.
    import editais.transporte_voyage as tv

    monkeypatch.setenv("VOYAGE_API_KEY", "chave-de-teste")

    trava = threading.Lock()
    em_voo = 0
    pico_em_voo = 0

    def _embeddar_lote_falso(lote: list[str], *args: object, **kwargs: object) -> list[list[float]]:
        nonlocal em_voo, pico_em_voo
        with trava:
            em_voo += 1
            pico_em_voo = max(pico_em_voo, em_voo)
        time.sleep(0.05)  # segura o lote em voo para forçar sobreposição real
        with trava:
            em_voo -= 1
        return [[float(len(texto))] for texto in lote]

    monkeypatch.setattr(tv, "_embeddar_lote", _embeddar_lote_falso)

    embedder = tv.criar_embedder_voyage(
        tamanho_lote=1,  # um lote por texto, para ter o que paralelizar
        segundos_entre_lotes=0.0,
        lotes_simultaneos=4,
        dormir=lambda _: None,
    )
    vetores = embedder(["a", "bb", "ccc", "dddd", "eeeee", "ffffff"])

    assert vetores == [[1.0], [2.0], [3.0], [4.0], [5.0], [6.0]]
    assert pico_em_voo > 1, "os lotes rodaram em série, não em paralelo"


def test_embedder_concorrente_mantem_o_espacamento_entre_lotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O risco de paralelizar é furar o rate limit: sem exclusão mútua, duas
    # threads leem o mesmo último-início e disparam juntas. Cada lote deve
    # reservar uma janela distinta.
    import editais.transporte_voyage as tv

    monkeypatch.setenv("VOYAGE_API_KEY", "chave-de-teste")
    monkeypatch.setattr(
        tv,
        "_embeddar_lote",
        lambda lote, *a, **k: [[float(len(t))] for t in lote],
    )

    esperas: list[float] = []
    trava = threading.Lock()

    def dormir_falso(segundos: float) -> None:
        with trava:
            esperas.append(segundos)

    embedder = tv.criar_embedder_voyage(
        tamanho_lote=1,
        segundos_entre_lotes=5.0,
        lotes_simultaneos=4,
        dormir=dormir_falso,
    )
    embedder(["a", "bb", "ccc", "dddd"])

    # 4 lotes: o primeiro sai na hora, os outros três esperam janelas
    # crescentes de ~5s, ~10s e ~15s — nenhum reaproveita a janela do outro.
    assert len(esperas) == 3
    esperas.sort()
    for posicao, espera in enumerate(esperas, start=1):
        assert espera == pytest.approx(5.0 * posicao, abs=0.5)
