from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from editais.analise_profunda import (
    ScoreAderencia,
    calcular_scores_aderencia,
    marcar_selecionados_para_revisao,
    serializar_analise_profunda,
)
from editais.chunks_de_editais import (
    EDITAIS_SIMULTANEOS_PADRAO,
    ProgressoDeEdital,
    obter_chunks_de_editais,
)
from editais.prioridade import carregar_perfil_prioridade
from editais.transporte_http import (
    baixar_arquivo_via_http,
    listar_arquivos_via_http,
    reiniciar_sessao,
)
from editais.transporte_voyage import MODELO_ANALISE_PROFUNDA, criar_embedder_voyage
from editais.triagem import (
    carregar_perfil,
    criar_embedder_com_cache,
)

DIRETORIO_DADOS = Path("dados")
DIRETORIO_PERFIL = Path("perfil/produtos-aurora")
DIRETORIO_PERFIL_PRIORIDADE = Path("perfil/prioridade")
DIRETORIO_DOCUMENTOS = DIRETORIO_DADOS / "documentos"
DIRETORIO_CHUNKS = DIRETORIO_DADOS / "chunks"
CACHE_CHUNKS = DIRETORIO_DADOS / ".embeddings" / "chunks.jsonl"
TOP_N_REVISAO = 20


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Análise profunda dos editais selecionados na triagem (Etapa 2)."
    )
    parser.add_argument(
        "--data",
        help="Data de referência no formato AAAA-MM-DD (padrão: ontem).",
        default=None,
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Processa apenas os N editais de maior Score de triagem (padrão: todos).",
    )
    parser.add_argument(
        "--editais-simultaneos",
        type=int,
        default=EDITAIS_SIMULTANEOS_PADRAO,
        help=(
            "Quantos editais baixar em paralelo "
            f"(padrão: {EDITAIS_SIMULTANEOS_PADRAO}; use 1 para voltar ao serial)."
        ),
    )
    args = parser.parse_args(argv)

    data_referencia = args.data or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    selecionados = _editais_selecionados(data_referencia, args.limite)
    editais_por_numero = _indexar_editais(data_referencia)

    # Cada worker segura no máximo uma conexão, então pool == concorrência é o
    # dimensionamento exato. Feito aqui, antes de qualquer worker existir — é a
    # precondição de reiniciar_sessao().
    reiniciar_sessao(tamanho_pool=max(args.editais_simultaneos, 1))

    def _relatar_progresso(progresso: ProgressoDeEdital) -> None:
        print(
            f"  [{progresso.concluidos}/{progresso.total}] "
            f"{progresso.numero}: {progresso.chunks} chunks",
            flush=True,
        )

    print(
        f"baixando e chunkando {len(selecionados)} editais "
        f"({args.editais_simultaneos} simultâneos)...",
        flush=True,
    )
    chunks_por_edital = obter_chunks_de_editais(
        selecionados,
        editais_por_numero,
        diretorio_chunks=DIRETORIO_CHUNKS,
        diretorio_documentos=DIRETORIO_DOCUMENTOS,
        listar=listar_arquivos_via_http,
        baixar=baixar_arquivo_via_http,
        editais_simultaneos=args.editais_simultaneos,
        ao_concluir=_relatar_progresso,
    )

    embedder_voyage = criar_embedder_voyage(modelo=MODELO_ANALISE_PROFUNDA)
    perfil = carregar_perfil(DIRETORIO_PERFIL, embedder_voyage, MODELO_ANALISE_PROFUNDA)
    perfil_prioridade = carregar_perfil_prioridade(
        DIRETORIO_PERFIL_PRIORIDADE, embedder_voyage, MODELO_ANALISE_PROFUNDA
    )
    embedder_de_chunks = criar_embedder_com_cache(
        embedder_voyage, CACHE_CHUNKS, MODELO_ANALISE_PROFUNDA
    )

    # Um edital por chamada, para dar visibilidade de progresso durante a fase
    # lenta (embedding sob rate limit) — sem isso, uma execução de horas não
    # imprime nada e é indistinguível de um processo travado.
    scores: list[ScoreAderencia] = []
    pulados = 0
    for posicao, (numero, chunks) in enumerate(chunks_por_edital.items(), start=1):
        print(
            f"  [{posicao}/{len(chunks_por_edital)}] embeddando {numero} "
            f"({len(chunks)} chunks)...",
            flush=True,
        )
        scores_do_edital = calcular_scores_aderencia(
            {numero: chunks}, embedder_de_chunks, perfil, perfil_prioridade
        )
        if not scores_do_edital:
            pulados += 1
            print(
                f"  [pulado] {numero}: falha persistente de embedding ou "
                f"orçamento de tempo por edital excedido",
                flush=True,
            )
        scores.extend(scores_do_edital)
    if pulados:
        print(f"  [aviso] {pulados} edital(is) pulado(s) por falha persistente de embedding")
    editais_analisados = marcar_selecionados_para_revisao(scores, n=TOP_N_REVISAO)

    saida = DIRETORIO_DADOS / f"analise_profunda_{data_referencia}.json"
    saida.write_text(
        json.dumps(
            serializar_analise_profunda(editais_analisados), ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    total_selecionados_para_revisao = sum(
        1 for e in editais_analisados if e.selecionado_para_revisao
    )
    print(
        f"Analisados {len(editais_analisados)} editais; {total_selecionados_para_revisao} "
        f"selecionados para revisão em {saida}"
    )


def _editais_selecionados(data_referencia: str, limite: int | None) -> list[str]:
    entrada = DIRETORIO_DADOS / f"triagem_{data_referencia}.json"
    triagem = json.loads(entrada.read_text(encoding="utf-8"))
    selecionados = [
        t for t in triagem if t.get("selecionado_para_analise_profunda")
    ]
    selecionados.sort(key=lambda t: t["score_triagem"], reverse=True)
    if limite is not None:
        selecionados = selecionados[:limite]
    return [t["numeroControlePNCP"] for t in selecionados]


def _indexar_editais(data_referencia: str) -> dict[str, dict[str, Any]]:
    entrada = DIRETORIO_DADOS / f"editais_{data_referencia}.json"
    editais = json.loads(entrada.read_text(encoding="utf-8"))
    return {e["numeroControlePNCP"]: e for e in editais}



if __name__ == "__main__":
    main()
