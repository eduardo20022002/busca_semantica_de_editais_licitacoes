"""Mede onde o PNCP satura, para escolher o teto de downloads simultâneos.

Por que existe: o PNCP não documenta rate limit. Diferente da Voyage — cujo
teto (2.000 RPM / 8M TPM do Tier 1) está publicado e permitiu dimensionar os
lotes do pré-embedding no papel —, aqui não há número oficial para dividir. A
alternativa a medir seria chutar a constante mais importante do desenho.

O que faz: baixa a MESMA amostra de arquivos reais com 1, 4, 8 e 16 workers
simultâneos e reporta, por nível, a vazão (MB/s e arquivos/s) e a taxa de
429/5xx. O teto a adotar é o ponto onde a vazão para de crescer
proporcionalmente OU onde a taxa de erro começa a subir — o que vier primeiro.

Repetir a mesma amostra em todos os níveis é de propósito: arquivos diferentes
têm tamanhos muito diferentes (mediana ~1,5 MB, cauda passando de 10 MB), então
comparar níveis com amostras distintas mediria a amostra, não a concorrência.

Uso:
    python scripts/medir_saturacao_pncp.py --data 2026-08-12 [--arquivos 24]

O resultado vai para a constante EDITAIS_SIMULTANEOS_PADRAO em
src/editais/chunks_de_editais.py — com o número medido no comentário, no mesmo
estilo já usado em transporte_voyage.py.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from editais.documentos import listar_arquivos
from editais.transporte_http import (
    baixar_arquivo_via_http,
    listar_arquivos_via_http,
    reiniciar_sessao,
)

DADOS = Path("dados")
NIVEIS_DE_CONCORRENCIA = (1, 4, 8, 16)
ARQUIVOS_NA_AMOSTRA_PADRAO = 24


def montar_amostra(data: str, quantidade: int) -> list[str]:
    """URLs de arquivos reais de editais selecionados para a Análise profunda."""
    triagem = json.loads((DADOS / f"triagem_{data}.json").read_text(encoding="utf-8"))
    editais = {
        e["numeroControlePNCP"]: e
        for e in json.loads((DADOS / f"editais_{data}.json").read_text(encoding="utf-8"))
    }
    selecionados = [t for t in triagem if t.get("selecionado_para_analise_profunda")]
    # Gerador próprio, não random.seed(): o módulo random é global e
    # documentos.py o usa para o jitter do backoff. Semear aqui tornaria o
    # jitter de produção determinístico — exatamente o contrário do que ele
    # existe para fazer.
    sorteio = random.Random(17)  # amostra estável entre rodadas, para comparar
    sorteio.shuffle(selecionados)

    urls: list[str] = []
    for item in selecionados:
        edital = editais.get(item["numeroControlePNCP"])
        if edital is None:
            continue
        resultado = listar_arquivos(
            edital["orgaoEntidade"]["cnpj"],
            edital["anoCompra"],
            edital["sequencialCompra"],
            listar_arquivos_via_http,
            dormir=time.sleep,
        )
        if resultado.erro is not None:
            continue
        # No máximo 2 arquivos por edital: um único edital com 30 anexos daria
        # uma amostra de um órgão só, e o que se quer medir é o PNCP sob a
        # variação real de latência entre órgãos diferentes.
        urls.extend(a.url for a in resultado.arquivos[:2])
        if len(urls) >= quantidade:
            break
    return urls[:quantidade]


def medir(urls: list[str], simultaneos: int) -> dict[str, float]:
    reiniciar_sessao(tamanho_pool=simultaneos)
    bytes_baixados = 0
    transitorios = 0
    falhas = 0

    def baixar_uma(url: str) -> tuple[int, int, int]:
        # Sem retry de propósito: o objetivo é observar a taxa BRUTA de 429/5xx
        # em cada nível. Com retry, o backoff esconderia justamente o sinal que
        # estamos tentando medir.
        resposta = baixar_arquivo_via_http(url)
        if resposta.status_code == 200 and resposta.conteudo is not None:
            return len(resposta.conteudo), 0, 0
        if resposta.status_code == 429 or resposta.status_code >= 500:
            return 0, 1, 0
        return 0, 0, 1

    comeco = time.monotonic()
    with ThreadPoolExecutor(max_workers=simultaneos) as executor:
        for tamanho, transitorio, falha in executor.map(baixar_uma, urls):
            bytes_baixados += tamanho
            transitorios += transitorio
            falhas += falha
    decorrido = time.monotonic() - comeco

    return {
        "simultaneos": simultaneos,
        "segundos": decorrido,
        "mb_por_s": (bytes_baixados / 1_048_576) / decorrido if decorrido else 0.0,
        "arquivos_por_s": len(urls) / decorrido if decorrido else 0.0,
        "transitorios": transitorios,
        "outras_falhas": falhas,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mede a saturação de download do PNCP.")
    parser.add_argument("--data", required=True, help="Data de referência (AAAA-MM-DD).")
    parser.add_argument(
        "--arquivos",
        type=int,
        default=ARQUIVOS_NA_AMOSTRA_PADRAO,
        help=f"Tamanho da amostra (padrão: {ARQUIVOS_NA_AMOSTRA_PADRAO}).",
    )
    args = parser.parse_args()

    print(f"montando amostra de {args.arquivos} arquivos...", flush=True)
    urls = montar_amostra(args.data, args.arquivos)
    if not urls:
        print("nenhum arquivo na amostra — a data tem triagem e editais coletados?")
        return
    print(f"{len(urls)} arquivos na amostra\n", flush=True)

    print(f"{'N':>3}  {'seg':>7}  {'MB/s':>7}  {'arq/s':>7}  {'429/5xx':>8}  {'falhas':>7}")
    medicoes = []
    for simultaneos in NIVEIS_DE_CONCORRENCIA:
        m = medir(urls, simultaneos)
        medicoes.append(m)
        print(
            f"{m['simultaneos']:>3.0f}  {m['segundos']:>7.1f}  {m['mb_por_s']:>7.2f}  "
            f"{m['arquivos_por_s']:>7.2f}  {m['transitorios']:>8.0f}  {m['outras_falhas']:>7.0f}",
            flush=True,
        )

    base = medicoes[0]["mb_por_s"]
    print("\nganho sobre o serial:")
    for m in medicoes:
        ganho = m["mb_por_s"] / base if base else 0.0
        ideal = m["simultaneos"]
        eficiencia = ganho / ideal * 100 if ideal else 0.0
        print(
            f"  N={m['simultaneos']:>3.0f}: {ganho:>5.2f}x  "
            f"({eficiencia:.0f}% do ganho linear ideal)"
        )
    print(
        "\nAdote o maior N cuja eficiência ainda seja alta e cuja coluna 429/5xx "
        "siga em zero.\nRegistre o resultado no comentário de "
        "EDITAIS_SIMULTANEOS_PADRAO (chunks_de_editais.py)."
    )


if __name__ == "__main__":
    main()
