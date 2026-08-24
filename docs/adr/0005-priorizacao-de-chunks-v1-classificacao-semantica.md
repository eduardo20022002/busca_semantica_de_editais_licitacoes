# V1 Priorização dos Chunks: classificação semântica em vez de palavra-chave

## O problema que motivou isso

O Score de aderência hoje é max pooling sobre **todos** os Chunks de um edital, sem distinção — inclusive os de boilerplate jurídico/administrativo/segurança. Isso já causou falsos positivos reais, observados rodando a Análise profunda contra os 100 editais do top-100 (V3 e V4): um edital de **manutenção de data center de um tribunal regional** (órgão do Judiciário, nada a ver com saúde) ficou entre os 2º-10º colocados dependendo da amostra, e editais de **exames/materiais de laboratório** (consumíveis, não TI) também pontuaram alto — porque bastou um único Chunk de linguagem genérica (proteção de dados, monitoramento de infraestrutura) "vencer" o max pooling contra algum vetor do Perfil Aurora.

O `CONTEXT.md` já previa a solução — **Prioridade de seção** (ALTA/MÉDIA/BAIXA por seção; BAIXA fica de fora da análise vetorial) — mas isso tinha sido deliberadamente adiado na primeira versão da Etapa 2, para simplificar a entrega inicial.

## A ideia: sentido, não palavra

A primeira abordagem cogitada foi detectar a prioridade por **palavra-chave no título da seção** (ex.: "DO OBJETO" → ALTA, "HABILITAÇÃO" → BAIXA), reaproveitando o detector de cabeçalho que já existe em `chunking.py`. Essa abordagem foi descartada: é binária (bate ou não bate a palavra exata) e frágil a qualquer edital que use formatação, numeração ou títulos de seção fora do padrão mais comum — perderíamos a classificação justamente nos casos fora da curva.

Decisão: classificar por **similaridade semântica**, reaproveitando a mesma arquitetura já usada para o Perfil Aurora (ADR-0002, multi-vetor por Aplicação Típica). A ideia:

- Criar um **Perfil de Prioridade** — um pequeno conjunto de frases-exemplo por categoria (ALTA, MÉDIA, BAIXA), cada uma representando o *sentido* daquela prioridade (não palavras exatas), embeddadas como vetores de referência. Exemplos de rascunho:
  - **ALTA**: "Esta seção descreve o objeto da contratação e suas especificações técnicas.", "Esta seção detalha o escopo do serviço ou produto a ser fornecido."
  - **BAIXA**: "Esta seção trata das condições de habilitação e documentação jurídica.", "Esta seção descreve penalidades, multas e sanções administrativas.", "Esta seção trata de garantias contratuais e condições de pagamento."
- Cada Chunk do edital — que **já é embeddado** para comparar contra o Perfil Aurora — é comparado por cosseno *também* contra os vetores do Perfil de Prioridade. A prioridade vencedora é a de maior similaridade.
- **Custo marginal zero de API**: como o vetor do Chunk já existe (calculado para o Score de aderência), a comparação com o Perfil de Prioridade é só mais uma operação de cosseno local — não precisa embeddar o Chunk de novo. O único custo novo é embeddar as ~10-15 frases-exemplo do Perfil de Prioridade, uma única vez (mesmo padrão de cache já usado para o Perfil Aurora).
- Caso ambíguo (as três distâncias ficam parecidas/baixas, nenhuma prioridade se destaca): default **MÉDIA** (inclui na análise) — o mesmo princípio já usado no design original: incluir demais é menos grave que excluir um Chunk relevante por engano.

Pendente de decidir antes da implementação: se ALTA e MÉDIA devem continuar tendo o mesmo efeito prático (ambas entram no max pooling, só BAIXA é excluída — como o `CONTEXT.md` define hoje) ou se essa distinção passa a ter peso diferente na pontuação; e o conteúdo final das frases-exemplo de cada categoria.

## Plano de validação

Não basta confiar na teoria — o plano de validação tem duas pernas, ambas usando dados reais já coletados durante a validação de hoje:

1. **Testes unitários com trechos reais rotulados à mão** — durante a leitura manual dos editais de hoje (ex.: o "DO OBJETO" do edital de telemedicina, o trecho jurídico do Termo de Referência do tribunal sobre sala-cofre/manutenção), já sabemos o que cada um *deveria* ser classificado. Vira um conjunto de teste (`pytest`) com fixtures de texto genuíno, no mesmo padrão dos testes já existentes (`test_chunking.py`, `test_triagem.py`).
2. **Comparação empírica antes/depois, na mesma base de 100 editais** — mesmo método que já validou a V3 do Perfil Aurora (ADR-0003, contra os 8.556 editais da base de teste). Rodar a Análise profunda de novo, agora com Prioridade de seção, sobre a mesma base do top100 (V3 ou V4) já processada sem ela, e verificar: os falsos positivos já identificados (data center do tribunal, exames/materiais de laboratório) caem no ranking? Os genuínos já confirmados (sistemas de gestão em saúde, telemedicina) se mantêm ou melhoram?

## Estado

Este documento registra o **plano e o raciocínio** discutidos em 2026-07-20 — ainda não implementado. Fica para uma sessão de `/mattpocock-skills:to-spec` + `/mattpocock-skills:implement` quando o desenho estiver fechado (frases-exemplo finais, decisão sobre ALTA vs MÉDIA).
