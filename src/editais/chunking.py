from __future__ import annotations

# ~500 tokens por Chunk a ~4 caracteres/token — extremo superior da faixa
# 256-512 tokens que benchmarks de RAG convergem como o "sweet spot" para
# busca semântica (chunks maiores, ~1000 tokens, diluem o sinal e prejudicam
# a precisão do max pooling contra o Perfil Aurora). ~15% de sobreposição
# entre Chunks consecutivos para não cortar uma frase-chave na fronteira.
CHUNK_ALVO_CARACTERES = 2000
SOBREPOSICAO_CARACTERES = 300
MIN_CARACTERES = 50

# Guarda contra a heurística de cabeçalho misfirar em conteúdo tabular. Ela
# pressupõe prosa com títulos; numa lista de itens ("729 6 UN AFASTADOR ANAL
# BIVALVE - DE AÇO INOX") ou numa planilha convertida, quase toda linha parece
# cabeçalho (curta e maiúscula) e vira uma seção própria — o resultado é um
# Chunk por linha, inútil para busca semântica e caríssimo para embeddar.
#
# Calibrado sobre os 289 editais de 2026-08-04: a mediana real é 977 chars por
# Chunk e o p5 é 364; os três casos degenerados observados tinham média de 99,
# 138 e 153 chars — um deles com 19.779 Chunks num único edital, que sozinho
# travou a Etapa 2 por mais de 15 minutos. As duas condições são necessárias:
# média baixa isolada só indica documento curto (vistos com 4 a 22 Chunks).
MINIMO_SECOES_PARA_SUSPEITA = 200
MEDIA_MINIMA_CARACTERES_POR_SECAO = 250


def chunkar_texto(texto: str) -> list[str]:
    secoes = _dividir_em_secoes(texto)
    if _fragmentacao_degenerada(secoes):
        # A heurística não se aplica a este texto: janela o conteúdo inteiro
        # como um bloco só, em vez de confiar em fronteiras que não existem.
        secoes = [texto]

    chunks: list[str] = []
    for secao in secoes:
        chunks.extend(_janelar(secao))
    return [c for c in chunks if len(c.strip()) >= MIN_CARACTERES]


def _fragmentacao_degenerada(secoes: list[str]) -> bool:
    if len(secoes) < MINIMO_SECOES_PARA_SUSPEITA:
        return False
    media = sum(len(s) for s in secoes) / len(secoes)
    return media < MEDIA_MINIMA_CARACTERES_POR_SECAO


def _dividir_em_secoes(texto: str) -> list[str]:
    secoes: list[list[str]] = []
    atual: list[str] = []
    for linha in texto.splitlines():
        if _e_cabecalho(linha) and atual:
            secoes.append(atual)
            atual = []
        atual.append(linha)
    if atual:
        secoes.append(atual)
    return ["\n".join(linhas).strip() for linhas in secoes]


def _e_cabecalho(linha: str) -> bool:
    linha = linha.strip()
    if not (3 <= len(linha) <= 80):
        return False
    letras = [c for c in linha if c.isalpha()]
    if len(letras) < 3:
        return False
    maiusculas = sum(1 for c in letras if c.isupper())
    return maiusculas / len(letras) >= 0.8


def _janelar(secao: str) -> list[str]:
    if len(secao) <= CHUNK_ALVO_CARACTERES:
        return [secao] if secao else []

    passo = CHUNK_ALVO_CARACTERES - SOBREPOSICAO_CARACTERES
    janelas: list[str] = []
    inicio = 0
    while inicio < len(secao):
        janelas.append(secao[inicio : inicio + CHUNK_ALVO_CARACTERES])
        if inicio + CHUNK_ALVO_CARACTERES >= len(secao):
            break
        inicio += passo
    return janelas
