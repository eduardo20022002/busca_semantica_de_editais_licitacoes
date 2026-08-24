from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

Embedder = Callable[[list[str]], list[list[float]]]

DIRETORIO_CACHE = ".embeddings"


@dataclass(frozen=True)
class Produto:
    nome: str
    vetor: list[float]


@dataclass(frozen=True)
class ScoreTriagem:
    numero_controle_pncp: str
    score_triagem: float
    produto_mais_proximo: str


@dataclass(frozen=True)
class EditalTriado:
    numero_controle_pncp: str
    score_triagem: float
    produto_mais_proximo: str
    selecionado_para_analise_profunda: bool


def marcar_selecionados(scores: list[ScoreTriagem], n: int) -> list[EditalTriado]:
    ordenados = sorted(scores, key=lambda s: s.score_triagem, reverse=True)
    return [
        EditalTriado(
            numero_controle_pncp=score.numero_controle_pncp,
            score_triagem=score.score_triagem,
            produto_mais_proximo=score.produto_mais_proximo,
            selecionado_para_analise_profunda=posicao < n,
        )
        for posicao, score in enumerate(ordenados)
    ]


SECAO_APLICACOES = "## Aplicações típicas"
SECAO_TERMOS = "## Tecnologias e termos relacionados"


def extrair_unidades_de_texto(conteudo_markdown: str) -> list[str]:
    # Regra assimétrica: cada bullet de aplicação típica vira sua própria unidade
    # (são casos de uso distintos), mas os termos relacionados viram uma unidade
    # só (é uma lista de sinônimos/jargão, não frases independentes).
    unidades = [
        linha.strip()[2:].strip()
        for linha in _corpo_da_secao(conteudo_markdown, SECAO_APLICACOES).splitlines()
        if linha.strip().startswith("- ")
    ]

    texto_termos = _corpo_da_secao(conteudo_markdown, SECAO_TERMOS).strip()
    if texto_termos:
        unidades.append(texto_termos)

    return unidades


def _corpo_da_secao(conteudo_markdown: str, titulo_secao: str) -> str:
    if titulo_secao not in conteudo_markdown:
        return ""
    apos_titulo = conteudo_markdown.split(titulo_secao, 1)[1]
    linhas_corpo: list[str] = []
    for linha in apos_titulo.splitlines():
        if linha.startswith("## "):
            break
        linhas_corpo.append(linha)
    return "\n".join(linhas_corpo)


def carregar_perfil(
    diretorio: Path, embedder: Embedder, modelo: str
) -> list[Produto]:
    pares = carregar_unidades_com_cache(diretorio, embedder, modelo, extrair_unidades_de_texto)
    return [Produto(nome=nome, vetor=vetor) for nome, vetor in pares]


def carregar_unidades_com_cache(
    diretorio: Path,
    embedder: Embedder,
    modelo: str,
    extrair_unidades: Callable[[str], list[str]],
) -> list[tuple[str, list[float]]]:
    # Mecanismo de carregamento/cache compartilhado entre o Perfil Aurora e o
    # Perfil de Prioridade (ADR-0005) — só o jeito de extrair unidades de texto
    # do markdown muda entre os dois domínios.
    diretorio_cache = diretorio / DIRETORIO_CACHE
    diretorio_cache.mkdir(exist_ok=True)

    arquivos = sorted(diretorio.glob("*.md"))
    conteudos = [arquivo.read_text(encoding="utf-8") for arquivo in arquivos]
    hashes = [hashlib.sha256(c.encode("utf-8")).hexdigest() for c in conteudos]

    unidades_por_arquivo: list[list[_UnidadeCacheada] | None] = []
    indices_a_embeddar: list[int] = []
    for indice, arquivo in enumerate(arquivos):
        cache = _ler_cache(diretorio_cache / f"{arquivo.stem}.json")
        if cache is not None and cache.hash == hashes[indice] and cache.modelo == modelo:
            unidades_por_arquivo.append(cache.unidades)
        else:
            unidades_por_arquivo.append(None)
            indices_a_embeddar.append(indice)

    for indice in indices_a_embeddar:
        textos = extrair_unidades(conteudos[indice])
        vetores = embedder(textos) if textos else []
        unidades = [
            _UnidadeCacheada(texto=texto, vetor=vetor) for texto, vetor in zip(textos, vetores)
        ]
        unidades_por_arquivo[indice] = unidades
        _gravar_cache(
            diretorio_cache / f"{arquivos[indice].stem}.json", hashes[indice], modelo, unidades
        )

    return [
        (arquivo.stem, unidade.vetor)
        for arquivo, unidades in zip(arquivos, unidades_por_arquivo)
        if unidades is not None
        for unidade in unidades
    ]


@dataclass(frozen=True)
class _UnidadeCacheada:
    texto: str
    vetor: list[float]


@dataclass(frozen=True)
class _CachePerfil:
    hash: str
    modelo: str
    unidades: list[_UnidadeCacheada]


def _ler_cache(caminho: Path) -> _CachePerfil | None:
    if not caminho.exists():
        return None
    dados: dict[str, Any] = json.loads(caminho.read_text(encoding="utf-8"))
    unidades = [_UnidadeCacheada(**unidade) for unidade in dados["unidades"]]
    return _CachePerfil(hash=dados["hash"], modelo=dados.get("modelo", ""), unidades=unidades)


def _gravar_cache(
    caminho: Path, hash_conteudo: str, modelo: str, unidades: list[_UnidadeCacheada]
) -> None:
    dados = {"hash": hash_conteudo, "modelo": modelo, "unidades": [asdict(u) for u in unidades]}
    caminho.write_text(json.dumps(dados), encoding="utf-8")


# Tamanho do grupo enviado por requisição à Voyage — enche um lote real do
# Tier 1 (até 1.000 textos por requisição). Persistir também acontece por
# grupo, mas desde que o cache virou append-only (ver _anexar_ao_cache) o
# custo de persistir deixou de depender do tamanho do cache acumulado.
TEXTOS_POR_PERSISTENCIA_PADRAO = 1_000

# Teto de tempo por chamada (na Análise profunda, uma chamada = um edital).
# Sem isso, um único edital gigante monopoliza a execução — visto na prática:
# um edital de 19.779 Chunks segurou a Etapa 2 por mais de 15 minutos. Ao
# estourar, levanta RuntimeError, que calcular_scores_aderencia já trata
# pulando o edital. O que foi embeddado até ali fica no cache, então uma
# reexecução retoma de onde parou em vez de recomeçar.
SEGUNDOS_MAXIMOS_POR_CHAMADA_PADRAO = 240.0


# O cache de embeddings é append-only (uma linha JSON por vetor), não um único
# objeto JSON reescrito a cada persistência.
#
# Achado real (2026-08-11): com o cache de Chunks em 1,19 GB, cada edital
# custava ~100s — praticamente todo esse tempo era serializar e reescrever o
# arquivo inteiro para gravar ~2,7 MB de vetores novos. O tempo por edital
# tinha deixado de depender do número de Chunks e passado a depender do
# tamanho do cache acumulado, projetando ~9h só para embeddar 300 editais.
# Anexar torna o custo proporcional ao que é novo, não ao que já existe.
#
# Vetores de outros modelos permanecem no arquivo e são ignorados na leitura —
# trocar de modelo não invalida o arquivo, só o que se lê dele.
def _ler_cache_de_vetores(caminho: Path, modelo: str) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if not caminho.exists():
        return cache
    with caminho.open(encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            registro = json.loads(linha)
            if registro.get("modelo") != modelo:
                continue
            cache[registro["hash"]] = registro["vetor"]
    return cache


def _anexar_ao_cache(
    caminho: Path, modelo: str, novos: list[tuple[str, list[float]]]
) -> None:
    if not novos:
        return
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as arquivo:
        for hash_texto, vetor in novos:
            arquivo.write(
                json.dumps({"modelo": modelo, "hash": hash_texto, "vetor": vetor}) + "\n"
            )


def criar_embedder_com_cache(
    embedder: Embedder,
    caminho_cache: Path,
    modelo: str,
    *,
    textos_por_persistencia: int = TEXTOS_POR_PERSISTENCIA_PADRAO,
    segundos_maximos_por_chamada: float = SEGUNDOS_MAXIMOS_POR_CHAMADA_PADRAO,
    relogio: Callable[[], float] = time.monotonic,
) -> Embedder:
    cache = _ler_cache_de_vetores(caminho_cache, modelo)

    def embedder_com_cache(textos: list[str]) -> list[list[float]]:
        hashes = [hashlib.sha256(texto.encode("utf-8")).hexdigest() for texto in textos]
        indices_faltantes = [i for i, h in enumerate(hashes) if h not in cache]

        # Persiste em grupos, não só ao final: uma falha persistente (ou um
        # processo morto) no meio de um edital grande não descarta os lotes já
        # embeddados com sucesso — a retomada continua de onde parou.
        comeco = relogio()
        for inicio in range(0, len(indices_faltantes), textos_por_persistencia):
            # Só cobra o orçamento a partir do segundo grupo: o primeiro sempre
            # roda, senão uma chamada poderia não avançar nada. Não dá para
            # interromper uma requisição em voo, então o corte é entre grupos.
            if inicio > 0 and relogio() - comeco > segundos_maximos_por_chamada:
                raise RuntimeError(
                    f"orçamento de {segundos_maximos_por_chamada:.0f}s por chamada "
                    f"excedido após {inicio} de {len(indices_faltantes)} textos"
                )
            grupo = indices_faltantes[inicio : inicio + textos_por_persistencia]
            novos_vetores = embedder([textos[i] for i in grupo])
            novos: list[tuple[str, list[float]]] = []
            for indice, vetor in zip(grupo, novos_vetores):
                # Um mesmo grupo pode repetir o mesmo texto; grava só a
                # primeira ocorrência para não inflar o arquivo com duplicatas.
                if hashes[indice] not in cache:
                    novos.append((hashes[indice], vetor))
                cache[hashes[indice]] = vetor
            _anexar_ao_cache(caminho_cache, modelo, novos)

        return [cache[h] for h in hashes]

    return embedder_com_cache


def serializar_triagem(editais_triados: list[EditalTriado]) -> list[dict[str, Any]]:
    return [
        {
            "numeroControlePNCP": e.numero_controle_pncp,
            "score_triagem": e.score_triagem,
            "produto_mais_proximo": e.produto_mais_proximo,
            "selecionado_para_analise_profunda": e.selecionado_para_analise_profunda,
        }
        for e in editais_triados
    ]


def calcular_scores_triagem(
    editais: list[dict[str, Any]],
    embedder: Embedder,
    perfil: list[Produto],
) -> list[ScoreTriagem]:
    objetos = [edital["objetoCompra"] for edital in editais]
    vetores = embedder(objetos)

    scores: list[ScoreTriagem] = []
    for edital, vetor_edital in zip(editais, vetores):
        melhor_produto = max(
            perfil,
            key=lambda produto: similaridade_cosseno(vetor_edital, produto.vetor),
        )
        scores.append(
            ScoreTriagem(
                numero_controle_pncp=edital["numeroControlePNCP"],
                score_triagem=similaridade_cosseno(vetor_edital, melhor_produto.vetor),
                produto_mais_proximo=melhor_produto.nome,
            )
        )
    return scores


def similaridade_cosseno(a: list[float], b: list[float]) -> float:
    produto = sum(x * y for x, y in zip(a, b))
    norma_a = math.sqrt(sum(x * x for x in a))
    norma_b = math.sqrt(sum(x * x for x in b))
    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0
    return produto / (norma_a * norma_b)
