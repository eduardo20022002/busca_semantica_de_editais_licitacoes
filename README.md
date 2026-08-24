# Busca semântica de editais de licitação

Pipeline que varre diariamente as licitações públicas brasileiras publicadas no [PNCP](https://pncp.gov.br) (Portal Nacional de Contratações Públicas) e encontra, entre milhares de editais novos por dia, os poucos que de fato interessam a uma empresa de tecnologia em saúde — sem que ninguém precise ler os outros 99%.

> **Nota:** este é um projeto de portfólio derivado de um sistema real que desenvolvi em produção. Nome da empresa, dados de negócio e endpoints internos foram substituídos por uma empresa fictícia ("Aurora Saúde") e valores de exemplo. A lógica, a arquitetura, as decisões técnicas e os números de desempenho são reais.

## O problema

O PNCP publica algo entre 1.500 e 2.000 novos editais por dia, de todos os setores — saúde, obras, alimentação, veículos, mão de obra, tecnologia genérica. Uma empresa que vende **software de gestão hospitalar, telessaúde, cloud, interoperabilidade, cibersegurança em saúde ou IA para saúde** precisa achar, nesse volume, os editais que compram exatamente isso — e perder um representa uma oportunidade comercial perdida.

Ler tudo manualmente não escala. Filtrar por palavra-chave falha de duas formas opostas:
- **Falso negativo**: um edital de telemedicina não necessariamente usa a palavra "telemedicina".
- **Falso positivo**: um edital de "soluções hospitalares" pode ser sobre soro fisiológico, não software.

## A solução: um funil de 4 estágios, cada um mais caro e mais preciso que o anterior

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Coleta    │ ──▶ │   Triagem   │ ──▶ │ Análise profunda  │ ──▶ │ Veredito (leitura │
│  ~1700/dia  │     │  top 300    │     │    top 20/dia     │     │  real dos docs)   │
└─────────────┘     └─────────────┘     └──────────────────┘     └──────────────────┘
   API do PNCP        embedding do          download + chunking      LLM lê o edital
   (paginado)         resumo do edital      + embedding completo     inteiro e decide
                       vs. Perfil Aurora     vs. Perfil Aurora        aderência real
```

1. **Coleta** — pagina a API pública do PNCP por dia e por modalidade de contratação, com retry e backoff para os limites de requisição do próprio portal.
2. **Triagem** — compara o embedding do resumo (`objetoCompra`) de cada edital contra um **Perfil de Produtos** (um vetor por "aplicação típica" de cada categoria de produto — ver [ADR-0002](docs/adr/0002-perfil-aurora-multi-vetor-por-aplicacao.md)) e corta para os 300 com maior similaridade. Sem baixar nenhum documento ainda — é o filtro barato.
3. **Análise profunda** — baixa os documentos completos dos 300 (Edital, Termo de Referência), extrai o texto, divide em Chunks por seção estrutural e recalcula o Score contra o mesmo Perfil, agora com o conteúdo real do edital, não só o resumo. Seleciona os 20 melhores para revisão.
4. **Veredito de aderência** — um LLM lê o conteúdo real dos 20 selecionados e decide, com justificativa, se o edital é genuinamente aderente. Necessário porque o Score por similaridade vetorial mede *proximidade de vocabulário*, não *o que está sendo comprado de fato* — ver [ADR-0007](docs/adr/0007-veredito-de-aderencia-por-leitura-dos-documentos.md), que documenta uma execução real onde **~90% do topo do Score era falso positivo**.

## Resultados medidos

Estes números vêm de execuções reais do pipeline, não de estimativa:

| Métrica | Valor |
|---|---|
| Editais processados por dia | ~1.700, cortados para 300 na Triagem |
| Falso positivo no topo do Score, sem leitura do documento | ~90% (ver ADR-0007) |
| Regressão real evitada: uma única palavra-gatilho ("medicamentos") no Perfil | dominava 91% do top-100 com editais de compra de remédio, não-TI (ver ADR-0003) |
| Tempo do pipeline completo (ponta a ponta, 300 editais) | ~2h20 → **~1h25** após as otimizações abaixo |
| Fase de embedding em lote, paralelizada | ~2h → **16,5 min** (~10x) |
| Fase de download de documentos, paralelizada | 1h36 → **~40-45 min** (2,2-2,3x) |

A otimização de download é o exemplo mais direto de **decisão orientada a medição em vez de suposição**: a expectativa inicial era um ganho de ~10x (por analogia com o embedding), mas um teste de saturação contra a API real do PNCP mostrou que o gargalo é **banda, não concorrência** — o throughput satura em ~2,5 MB/s com apenas 4 downloads simultâneos, sem nenhum erro de limite de requisição em nenhum nível testado. Subir a concorrência além disso não compra nada. A spec original foi corrigida com o resultado medido em vez de mantida com a expectativa errada.

## Decisões de engenharia que valem a leitura

Cada decisão não-óbvia do projeto está documentada como ADR, com o raciocínio e — sempre que possível — o dado real que motivou a escolha:

- [**ADR-0001**](docs/adr/0001-voyage-ai-para-embeddings.md) — escolha do provedor de embeddings e navegação de rate limits sem cartão de crédito cadastrado.
- [**ADR-0002**](docs/adr/0002-perfil-aurora-multi-vetor-por-aplicacao.md) — por que um vetor por produto (média do documento inteiro) falha, e por que múltiplos vetores por caso de uso resolve.
- [**ADR-0005**](docs/adr/0005-priorizacao-de-chunks-v1-classificacao-semantica.md) — classificar a prioridade de uma seção do edital por *sentido* (similaridade semântica), não por palavra-chave no título.
- [**ADR-0006**](docs/adr/0006-selecao-de-documentos-principais-por-tipo.md) — usar o campo de tipo de documento padronizado pela Lei 14.133/2021 em vez de heurística de nome de arquivo.
- [**ADR-0007**](docs/adr/0007-veredito-de-aderencia-por-leitura-dos-documentos.md) — por que o Score sozinho não decide aderência, e por que a leitura real do documento é indispensável.

O vocabulário do domínio (Edital, Chunk, Score de triagem, Score de aderência, Veredito de aderência, Falso positivo do Score, e mais) está fixado em [`CONTEXT.md`](CONTEXT.md) — um glossário vivo que qualquer pessoa (ou agente de IA) trabalhando no código deveria consultar antes de nomear um conceito novo.

## Arquitetura de código

```
src/editais/
├── coleta.py              # Etapa 1: paginação da API do PNCP
├── triagem.py              # Etapa 2: Score de triagem (embedding do resumo)
├── documentos.py           # Listagem e download de arquivos de um edital
├── chunking.py             # Divisão estrutural de um documento em Chunks
├── extracao.py             # Extração de texto de PDF/DOCX
├── chunks_de_editais.py    # Etapa 3: download + chunking, paralelizado por edital
├── analise_profunda.py     # Etapa 3: Score de aderência final
├── transporte_http.py      # Sessão HTTP compartilhada (pool de conexões)
├── transporte_voyage.py    # Cliente do provedor de embeddings, com pacing/lotes
└── cli_*.py                # Entradas de linha de comando de cada etapa

scripts/
├── medir_saturacao_pncp.py     # Mede o teto real de concorrência contra o PNCP
├── preembeddar_chunks.py       # Embedding em lote paralelo (~10x)
├── enviar_painel.py             # Envia o resultado final a um backend externo
└── pipeline_completo.py         # Orquestra as 4 etapas em sequência

perfil/produtos-aurora/     # Um markdown por categoria de produto (o "Perfil")
docs/adr/                   # Decisões de arquitetura, uma por arquivo
tests/                      # Suíte de testes (138 testes, TDD com dependências injetadas)
```

## Como rodar

```bash
git clone <este-repositório>
cd busca_semantica_de_editais_licitacoes
cp .env.example .env   # preencha com suas próprias chaves
uv sync                 # ou: pip install -e .

# Testes + typecheck
PYTHONPATH=src uv run pytest -q
uv run mypy src tests

# Pipeline completo de um dia
PYTHONPATH=src uv run python -m editais.cli_coleta --data 2026-08-14
PYTHONPATH=src uv run python -m editais.cli_triagem --data 2026-08-14
PYTHONPATH=src uv run python -m editais.cli_analise_profunda --data 2026-08-14
```

## Stack

Python 3.11+, [Voyage AI](https://voyageai.com) para embeddings (recomendado pela própria Anthropic para uso com Claude), API pública do PNCP, `pypdf`/`python-docx` para extração de texto, `pytest` + `mypy` para qualidade, e um LLM (Claude) para o julgamento final de aderência.

## Metodologia de desenvolvimento

Este projeto foi construído com um agente de IA (Claude Code) como par de desenvolvimento constante — não só para gerar código, mas para manter a disciplina de TDD, escrever e revisar as decisões de arquitetura (ADRs) no momento em que eram tomadas, e rodar medições reais antes de otimizar. `CLAUDE.md` e `docs/agents/` documentam como esse fluxo de trabalho foi estruturado.

## Licença

MIT — ver [LICENSE](LICENSE).
