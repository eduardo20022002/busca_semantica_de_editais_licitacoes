# Busca Semântica de Editais

Pipeline automatizado (sem human in the loop) de busca, análise e classificação de editais de licitação aderentes ao escopo de atuação da Aurora.

## Language

**Edital**:
Uma licitação publicada no PNCP, identificada de forma única pelo `numeroControlePNCP`. É a unidade central do pipeline — sobre ela recaem Score de triagem, Score de aderência, Chunks, Veredito de aderência e a marcação do analista.

**Reprocessamento**:
Regra de idempotência entre execuções diárias da coleta: um Edital já processado não é reprocessado, a menos que seus documentos ou data de atualização tenham mudado desde a última execução (retificação).
_Avoid_: reexecução, recomputação

**Edital aderente**:
Um edital que recebeu Veredito de aderência positivo — ou seja, cujo conteúdo real cai dentro do Escopo Aurora, mesmo que o item dentro do escopo não seja o objeto principal ou predominante do edital. Aderência é uma conclusão sobre o conteúdo, nunca sobre o Score: um Score de aderência alto seleciona o edital para revisão, não o torna aderente.
_Avoid_: edital relevante, edital compatível, edital bem pontuado

**Edital selecionado para revisão**:
Um edital cujo Score de aderência está entre os top-N do dia, tornando-o elegível para receber um Veredito de aderência. É um recorte de custo — quantos editais conseguimos revisar —, não um julgamento de mérito.
_Avoid_: edital aderente (para este sentido), edital aprovado

**Score de aderência**:
Valor numérico atribuído a cada edital buscado no PNCP, calculado por max pooling — a maior similaridade de cosseno entre qualquer Chunk do edital e qualquer vetor de Aplicação Típica de qualquer Produto Aurora. Calculado sem LLM. Serve para **priorizar** quais editais recebem Veredito de aderência; não decide aderência por si só, porque mede proximidade de vocabulário, não de objeto contratado.
_Avoid_: pontuação, ranking, nota

**Score de triagem**:
Score preliminar calculado a partir do embedding do campo `objetoCompra` (resumo do edital retornado pela listagem do PNCP, sem baixar nenhum documento), comparado contra o Perfil Aurora. Decide quais editais avançam para a Análise profunda. O corte é por **top-N do dia** (os N editais de maior Score de triagem, hoje N=100), não por um valor absoluto de similaridade — evita depender de calibração que ainda não temos e limita o custo de forma previsível. N é reavaliado conforme a capacidade de processamento disponível (hoje limitada; deve crescer se houver infraestrutura dedicada rodando em lote, ex. à noite).
_Avoid_: pré-score, score de filtro, corte mínimo de triagem

**Análise profunda**:
A etapa que baixa os documentos completos de um edital que passou do Score de triagem, aplica chunking estrutural e calcula o Score de aderência final por max pooling entre Chunks e Produtos Aurora.
_Avoid_: análise completa, etapa 2

**Chunk**:
Um trecho de texto extraído de um documento de edital — por seção estrutural detectada (ex: "DO OBJETO") ou por janela deslizante quando não há cabeçalho reconhecível — usado como unidade de comparação vetorial contra o Perfil Aurora.

**Prioridade de seção**:
Classificação (ALTA, MÉDIA ou BAIXA) atribuída a cada seção de um edital. Seções ALTA/MÉDIA geram Chunks com embedding; seções BAIXA (habilitação, garantias, penalidades, condições de pagamento) têm o texto extraído e guardado, mas não entram na análise vetorial.

**Perfil Aurora**:
O conjunto de Produtos Aurora usado como referência para calcular o Score de aderência.

**Produto Aurora**:
Uma solução ou produto da Aurora, descrito em um arquivo markdown próprio em `perfil/produtos-aurora/`, representado por **múltiplos vetores de embedding** — um por Aplicação Típica mais um para a lista de termos relacionados (ADR-0002) — nunca um vetor médio do documento inteiro, nem uma média entre produtos. O Score de triagem e o Score de aderência usam max pooling contra todas essas sub-unidades; o nome do produto reportado (`produto_mais_proximo`) é sempre agregado no nível de produto, nunca o texto da sub-unidade vencedora.
_Avoid_: vetor do produto (no singular, quando o contexto é embedding)

**Aplicação Típica**:
Uma sub-unidade de um Produto Aurora — um bullet de caso de uso concreto (ou a lista de termos relacionados) dentro do arquivo markdown do produto, embeddada como seu próprio vetor. Existe para evitar a diluição semântica de embeddar o documento inteiro como um só vetor (ADR-0002).

**Routine**:
A etapa final do pipeline, que roda sobre os Editais selecionados para revisão. Um LLM lê o conteúdo real dos documentos de cada edital e produz duas saídas: o Veredito de aderência e a Justificativa semântica. Não recalcula nem ajusta o Score de aderência.
_Avoid_: pipeline de LLM, etapa de análise

**Veredito de aderência**:
A marcação binária — aderente ou não aderente — atribuída a um Edital selecionado para revisão ao final da Routine, decidida pela leitura do conteúdo real dos documentos confrontado com o Escopo Aurora. Publicado no Painel de Analistas como `ia_aderente`. Distinto da marcação do analista, que é humana e nunca é sobrescrita pelo pipeline.
_Avoid_: classificação, flag de aderência, status

**Justificativa semântica**:
O texto curto que acompanha o Veredito de aderência, explicando com base no objeto real por que o edital é ou não aderente. Quando o veredito é negativo, nomeia o padrão de falso positivo observado (mão de obra assistencial, hardware ou insumo, serviço de saúde sem TI, sistema genérico sem recorte de saúde).
_Avoid_: justificativa da IA, explicação, parecer

**Falso positivo do Score**:
Um edital com Score de aderência alto que a Routine marca como não aderente — o vocabulário do edital se parece com o do Perfil Aurora, mas o objeto contratado está fora do Escopo Aurora. É o caso majoritário no topo do Score, não a exceção.

**Painel de Analistas**:
O sistema interno da Aurora que recebe o resultado do pipeline por API e o apresenta aos analistas, guardando lado a lado o Veredito de aderência (do pipeline) e a marcação do analista (humana).
_Avoid_: o backend, o sistema, a plataforma

**Escopo Aurora**:
As categorias de Tecnologia da Informação aplicada à Saúde que tornam um edital aderente: IA para Saúde, Software de Gestão em Saúde, Telessaúde, Cloud para Saúde, Interoperabilidade em Saúde, e Cibersegurança em Saúde.
_Avoid_: área de atuação, nicho

**IA para Saúde**:
Categoria do Escopo Aurora cobrindo diagnóstico assistido, triagem, apoio à decisão clínica e algoritmos preditivos aplicados à saúde.

**Software de Gestão em Saúde**:
Categoria do Escopo Aurora cobrindo gestão hospitalar, prontuário eletrônico (PEP), ERP hospitalar, e gestão de leitos/agenda/faturamento em saúde.

**Telessaúde**:
Categoria do Escopo Aurora cobrindo teleconsulta, telelaudo, telemonitoramento e qualquer modalidade "tele-" ligada à saúde.

**Cloud para Saúde**:
Categoria do Escopo Aurora cobrindo provisionamento e infraestrutura de nuvem para armazenamento e processamento de dados de saúde.

**Interoperabilidade em Saúde**:
Categoria do Escopo Aurora cobrindo integração de sistemas de saúde via padrões como FHIR e HL7.

**Cibersegurança em Saúde**:
Categoria do Escopo Aurora cobrindo proteção de dados de saúde e conformidade com sigilo médico/LGPD aplicada a sistemas de saúde.
