# Voyage AI para embeddings

Precisamos de embeddings de `objetoCompra`, Chunks de editais e Produtos Aurora majoritariamente em português. Escolhemos a Voyage AI porque é a provedora de embeddings oficialmente recomendada pela própria Anthropic — Claude não tem modelo de embeddings próprio.

Usamos a **série 4** da Voyage: conforme a tabela oficial de preços (docs.voyageai.com/docs/pricing), `voyage-4-large`, `voyage-4`, `voyage-4-lite`, `voyage-context-3` e `voyage-code-3` têm 200 milhões de tokens grátis por conta; `voyage-multilingual-2` e outros têm 50 milhões grátis. Modelos listados como "Older models" (incluindo `voyage-3.5-lite`, que chegamos a usar por engano numa correção anterior deste ADR, e `voyage-multilingual-2`, escolha original) **não têm tokens grátis nenhum** — são cobrados desde o primeiro token. No Score de triagem (alto volume) usamos `voyage-4-lite` (otimizado para latência/custo, gratuito); a Análise profunda (volume menor, top-N do dia, resultado vira o Score de aderência visto pelo analista) usará `voyage-4` (melhor qualidade, também gratuito), a confirmar na spec daquela etapa. Os dois lados de cada comparação de cosseno precisam usar o mesmo modelo.

Sem método de pagamento cadastrado, a conta opera com rate limit reduzido (3 requisições/min, 10 mil tokens/min) — o pipeline respeita esse teto de forma proativa e configurável, para subir o limite sem mudar a lógica quando um cartão for cadastrado.

Essa escolha é cara de reverter — trocar de provedor ou de modelo exige reembeddar todo o histórico já processado — então fica registrada aqui em vez de implícita no código.

## Atualização (2026-08-05): cartão cadastrado, Tier 1

Cadastrado método de pagamento na conta Voyage. Confirmado por teste real (lote de 300 chunks, ~92,6K tokens estimados, HTTP 200 em 2,86s): o rate limit subiu para o Tier 1 (2.000 RPM / 8M TPM no `voyage-4`, o mais apertado dos dois modelos em uso). **Os 200 milhões de tokens grátis por conta continuam valendo** — cadastrar cartão não gasta esse saldo, só libera a taxa maior; cobrança só ocorreria se esse saldo se esgotasse.

Antes de chegar a essa decisão, avaliamos trocar de provedor (Gemini Embedding, chave já disponível) para contornar o rate limit sem cartão. Descartado por dois motivos: (1) embeddings só são comparáveis dentro do mesmo modelo — trocar exigiria reembeddar o Perfil Aurora e o Perfil de Prioridade inteiros, não só os Chunks; (2) o tier grátis do Gemini tem uma armadilha real — o "1.000 RPD" documentado é contado por **texto embeddado**, não por chamada de API (confirmado num teste que recebeu 429 "`embed_content_free_tier_requests`, limit: 1000" depois de só ~830 textos). Isso o torna inviável para o volume do pipeline (~21 dias para reembeddar a base de teste de 100 editais, e nem cobre um dia de produção real).

Parâmetros de pacing atualizados em `transporte_voyage.py` (`TAMANHO_LOTE_PADRAO`, `TOKENS_MAXIMOS_POR_LOTE_PADRAO`, `SEGUNDOS_ENTRE_LOTES_PADRAO`) para refletir o Tier 1.
