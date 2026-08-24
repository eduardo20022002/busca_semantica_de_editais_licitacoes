# Seleção de documentos principais por tipo (reverte parte da decisão original da Etapa 2)

A spec original da Etapa 2 (issue #4) decidiu deliberadamente **baixar e embeddar todos os arquivos** listados pelo PNCP para um edital, sem filtrar por nome ou tipo — a justificativa registrada foi: *"filtrar por nome de arquivo é frágil — nomenclatura não é padronizada entre órgãos"*. Na época, a única informação disponível pra distinguir um arquivo de outro era o nome do arquivo em si (ex. `"EDITAL-PROC-028-2026...pdf"`, `"PLANILHA-ORCAMENTARIA.pdf"`), o que de fato não é confiável.

Durante a validação da Prioridade de seção V1 (ver ADR-0005), ao investigar como a Etapa da Routine deveria ler os documentos de um edital, redescobrimos que o endpoint de listagem de arquivos do PNCP (`/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos`) **já retorna um campo de tipo padronizado** (`tipoDocumentoNome`, junto de `tipoDocumentoId`), definido pela própria Lei 14.133/2021 — não é heurística de nome de arquivo, é a classificação que o órgão contratante atribuiu ao publicar o documento. Valores reais observados: "Edital", "Termo de Referência", "Projeto Básico", "Estudo Técnico Preliminar", "Outros Documentos".

Essa informação já é capturada pelo `documentos.py` desde a implementação original da Etapa 2 (campo `tipo_documento_nome` em `ArquivoEdital`), mas nunca foi usada para filtrar — só pra exibição em log.

## Decisão

Continuar baixando todos os arquivos de um edital (sem mudança — é barato e útil pra auditoria/arquivo), mas passar a **filtrar quais arquivos entram na extração/chunking/embedding**, restringindo aos que de fato descrevem o objeto contratado: "Edital" + "Termo de Referência"; na ausência de Termo de Referência, cai para "Projeto Básico"; na ausência de ambos, cai para "Estudo Técnico Preliminar". Se nenhum desses três tipos existir, o edital é tratado como sem documento principal disponível (mesmo tratamento de qualquer outra lacuna de conteúdo).

## Por que isso é seguro reverter agora

- O sinal de tipo é confiável (vocabulário padronizado da lei, não texto livre).
- Reduz significativamente o volume de Chunks/tokens embeddados por edital, sem perder o conteúdo que descreve o objeto.
- Complementa (não substitui) a Prioridade de seção V1: o boilerplate jurídico/administrativo que hoje aparece como anexo separado (planilhas, pareceres, minutas de contrato) deixa de ser embeddado; o boilerplate que aparece **dentro** do próprio Edital/TR (habilitação, garantias, confidencialidade) continua existindo e continua sendo tratado pela Prioridade de seção.
- Nos dois falsos positivos reais confirmados até agora (data center de um tribunal, exames laboratoriais), o Chunk problemático estava dentro do próprio Edital/TR — essa mudança não teria evitado esses casos sozinha, mas reduz o volume geral de conteúdo irrelevante que o pipeline processa.
