"""Valida a Etapa 2 (Análise profunda) contra os 100 editais do top-100 de uma
versão do Perfil Aurora (V3 ou V4).

Reutiliza os módulos de produção (documentos, extracao, chunking,
analise_profunda) exatamente como o cli_analise_profunda faria, mas cruzando os
5 arquivos diários `dados/editais_2026-07-0[6-10].json` (as triagens V3/V4
abrangem 06-10/07). Não é código de produção — é um harness de validação/experimento.

Uso (rodar da raiz do repo):
    PYTHONPATH=src uv run python scripts/validar_v3_top100.py [N] [fase] [versao]
      N       quantos editais (por ordem de score decrescente); padrão 100
      fase    'baixar' (só baixa+chunka), 'tudo' (baixa+embedda+ranqueia); padrão tudo
      versao  'v3' ou 'v4' — qual top100_{versao}.json usar como entrada e qual
              dados/analise_profunda_{versao}_top.json escrever; padrão v3

Resumível: os chunks de cada edital ficam em dados/chunks/ e os embeddings em
dados/.embeddings/chunks.json — rodar de novo reaproveita o cache e continua de
onde parou. O ranking parcial é reescrito em dados/analise_profunda_{versao}_top.json
a cada edital, então um run interrompido pelo rate limit já deixa "top-N até
agora" em disco.
"""
from __future__ import annotations

import glob
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from editais.analise_profunda import calcular_scores_aderencia, serializar_analise_profunda
from editais.chunking import chunkar_texto
from editais.documentos import baixar_arquivo, listar_arquivos, nome_de_arquivo_seguro
from editais.extracao import extrair_textos_de_arquivo
from editais.transporte_http import baixar_arquivo_via_http, listar_arquivos_via_http
from editais.transporte_voyage import MODELO_ANALISE_PROFUNDA, criar_embedder_voyage
from editais.triagem import carregar_perfil, criar_embedder_com_cache

DADOS = Path("dados")
CHUNKS_DIR = DADOS / "chunks"
DOCS_DIR = DADOS / "documentos"

# Teto de chunks embeddados por edital, só para esta validação sob rate limit:
# impede que um único anexo gigante (ex. planilha de dimensionamento de 5MB que
# vira 246k chunks) monopolize horas de embedding. O cache mantém todos os
# chunks; o corte afeta só o que entra no max pooling — como o Score de aderência
# é o maior cosseno, o objeto/specs (nos primeiros arquivos) já domina. O cap
# NÃO é do pipeline de produção (ver o chip "Cap chunk explosion").
MAX_CHUNKS_EMBED = 250


def slug(t: str) -> str:
    return t.replace("/", "_").replace("\\", "_")


def indexar_editais() -> dict[str, dict]:
    idx = {}
    for f in sorted(glob.glob("dados/editais_2026-07-*.json")):
        for e in json.load(open(f, encoding="utf-8")):
            idx[e["numeroControlePNCP"]] = e
    return idx


def obter_chunks(numero: str, edital: dict, chunks_dir: Path, docs_dir: Path) -> list[str]:
    cache = chunks_dir / f"{slug(numero)}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["chunks"]

    cnpj = edital["orgaoEntidade"]["cnpj"]
    ano = edital["anoCompra"]
    seq = edital["sequencialCompra"]
    res = listar_arquivos(cnpj, ano, seq, listar_arquivos_via_http, dormir=time.sleep)
    if res.erro:
        print(f"  [erro-listar] {numero}: {res.erro}", flush=True)
        chunks: list[str] = []
    else:
        dedir = docs_dir / slug(numero)
        dedir.mkdir(parents=True, exist_ok=True)
        textos: list[str] = []
        for arq in res.arquivos:
            baixado = baixar_arquivo(arq.url, baixar_arquivo_via_http, dormir=time.sleep)
            if baixado is None:
                print(f"  [erro-baixar] {numero}: {arq.titulo}", flush=True)
                continue
            nome = baixado.nome_arquivo or arq.titulo
            nome_seguro = nome_de_arquivo_seguro(nome)
            (dedir / f"{arq.sequencial_documento}_{nome_seguro}").write_bytes(baixado.conteudo)
            ext = extrair_textos_de_arquivo(nome, baixado.conteudo)
            if not ext:
                print(f"  [pulado] {numero}: sem texto de '{nome}'", flush=True)
            textos.extend(t.texto for t in ext)
        chunks = chunkar_texto("\n".join(textos))

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {"dataAtualizacaoGlobal": edital.get("dataAtualizacaoGlobal", ""), "chunks": chunks},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return chunks


def main() -> None:
    n_limite = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    fase = sys.argv[2] if len(sys.argv) > 2 else "tudo"  # baixar | tudo
    versao = sys.argv[3] if len(sys.argv) > 3 else "v3"  # v3 | v4
    if versao not in ("v3", "v4"):
        raise SystemExit(f"versao inválida: {versao!r} (use 'v3' ou 'v4')")
    campo_score = f"score_{versao}"

    # V3 usa o cache local em dados/ (não versionado); V4 usa a base já baixada
    # e commitada no repo em base-teste/analise-profunda-v4/ (documentos e
    # chunks dos 100 editais do top100_v4, ~391MB, extraída por outra sessão).
    if versao == "v4":
        chunks_dir = Path("base-teste/analise-profunda-v4/chunks")
        docs_dir = Path("base-teste/analise-profunda-v4/documentos")
    else:
        chunks_dir = CHUNKS_DIR
        docs_dir = DOCS_DIR

    top = json.load(
        open(f"base-teste/comparacao-v1-v2-v3/top100_{versao}.json", encoding="utf-8")
    )
    top.sort(key=lambda e: e[campo_score], reverse=True)
    top = top[:n_limite]
    idx = indexar_editais()

    chunks_por_edital: dict[str, list[str]] = {}
    total_chunks = 0
    erros_listar = 0
    for i, e in enumerate(top, 1):
        numero = e["numeroControlePNCP"]
        ch = obter_chunks(numero, idx[numero], chunks_dir, docs_dir)
        chunks_por_edital[numero] = ch
        total_chunks += len(ch)
        if not ch:
            erros_listar += 1
        print(
            f"[{i}/{len(top)}] {numero}: {len(ch)} chunks ({campo_score}={e[campo_score]:.3f})",
            flush=True,
        )

    print(f"\nTOTAL: {len(top)} editais, {total_chunks} chunks, {erros_listar} sem chunks", flush=True)
    if fase == "baixar":
        return

    # Tier grátis da Voyage: 3 RPM (1 req/20s) E 10K TPM. Com 62s de espaçamento
    # e lote de 4000 tokens estimados, usávamos só ~3.871 TPM (~39% do teto real)
    # — conservador demais, escolhido quando uma falha ainda derrubava o run
    # inteiro. Agora que o loop principal pula (não derruba) um edital que falhe
    # (ver "pulado-erro"), o custo de ser mais agressivo caiu bastante: 35s de
    # espaçamento usa ~6.857 TPM estimados (~69% do teto), ainda com margem para
    # a estimativa de tokens (len//4) subcontar o real, e segue bem acima do piso
    # de 20s do 3 RPM.
    embedder = criar_embedder_voyage(
        modelo=MODELO_ANALISE_PROFUNDA,
        tokens_maximos_por_lote=4000,
        segundos_entre_lotes=35,
        max_tentativas=8,
        espera_base_segundos=10,
        espera_maxima_segundos=60,
    )
    perfil = carregar_perfil(Path("perfil/produtos-aurora"), embedder, MODELO_ANALISE_PROFUNDA)
    emb_chunks = criar_embedder_com_cache(embedder, DADOS / ".embeddings" / "chunks.json", MODELO_ANALISE_PROFUNDA)

    # Incremental e resumível: embedda um edital por vez (editais em ordem de
    # score decrescente), reescrevendo o ranking a cada edital — assim um run
    # interrompido pelo rate limit ainda deixa "top-N até agora" em disco, e
    # rodar de novo reaproveita o cache de embeddings e continua de onde parou.
    saida = DADOS / f"analise_profunda_{versao}_top.json"
    objeto = {e["numeroControlePNCP"]: e["objetoCompra"] for e in top}
    scores = []
    for i, (numero, ch) in enumerate(chunks_por_edital.items(), 1):
        ch_cap = ch[:MAX_CHUNKS_EMBED]
        if len(ch) > MAX_CHUNKS_EMBED:
            print(f"  [cap] {numero}: {len(ch)} chunks -> {MAX_CHUNKS_EMBED} embeddados", flush=True)
        try:
            um = calcular_scores_aderencia({numero: ch_cap}, emb_chunks, perfil)[0]
        except RuntimeError as erro:
            # Um edital problemático (rate limit persistente, etc.) não deve
            # derrubar os outros 99 — pula, registra, e tenta de novo numa
            # próxima execução (o cache de embeddings preserva o que já deu certo).
            print(f"  [pulado-erro] {numero}: {erro}", flush=True)
            continue
        scores.append(um)
        saida.write_text(
            json.dumps(serializar_analise_profunda(scores), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[embed {i}/{len(chunks_por_edital)}] {numero}: "
            f"aderência={um.score_aderencia:.3f} [{um.produto_mais_proximo}]",
            flush=True,
        )

    print(f"\nRanking salvo em {saida}", flush=True)
    print("\n=== TOP 15 por Score de aderência (conteúdo real) ===", flush=True)
    for r in serializar_analise_profunda(scores)[:15]:
        print(
            f"{r['score_aderencia']:.3f}  {r['produto_mais_proximo']:<34} | "
            f"{objeto[r['numeroControlePNCP']][:64]}",
            flush=True,
        )


if __name__ == "__main__":
    main()
