# Veredito de aderência vem da leitura dos documentos, não do Score

O Score de aderência mede proximidade de vocabulário entre os Chunks de um edital e o Perfil Aurora, e por isso não distingue "sistema de telessaúde" de "contratação de médicos para plantão" — os dois falam de atendimento, especialidades e saúde. Na execução de 04/08/2026, dos 22 editais mais bem pontuados apenas 2 eram genuinamente aderentes: **~90% de falso positivo no topo do Score**. Decidimos, portanto, que a Routine fecha o pipeline lendo o conteúdo real dos documentos de cada Edital selecionado para revisão e emitindo um Veredito de aderência binário, publicado no Painel de Analistas como `ia_aderente` junto de uma Justificativa semântica.

## Considered Options

- **Confiar no Score e publicar o top-N como aderente.** Rejeitado: entregaria aos analistas uma lista majoritariamente errada, e o custo de revisar 20 falsos positivos por dia anula o ganho do pipeline.
- **Julgar apenas pelo `objetoCompra` da listagem do PNCP.** Muito mais barato (sem download nem extração), mas o campo é frequentemente truncado ou genérico demais. Caso concreto: `60448040000122-1-000511/2026` traz `"COMPONENTES PARA EQUIPAMENTOS MEDICO HOSPITALARES SEM NOTIFI"`, enquanto o edital revela que o objeto real é *cabos e lâminas de laringoscópio*. Julgar pelo objeto teria produzido um veredito baseado numa frase cortada no meio.
- **Ler os documentos reais (escolhido).** Caro, mas é a única fonte que descreve o que está sendo contratado.

## Consequences

- O Veredito de aderência convive com a marcação do analista no Painel de Analistas como campos separados: o pipeline nunca sobrescreve a avaliação humana, e reenvios preservam correções feitas à mão.
- Um edital sem leitura disponível deve **omitir** `ia_aderente` no envio, e não mandar `null` — omitir preserva o valor atual no Painel de Analistas; `null` apagaria a correção de um analista.
- Os padrões recorrentes de falso positivo já observados (mão de obra assistencial, hardware ou insumo, serviço de saúde sem TI, sistema genérico sem recorte de saúde) servem de checklist para a Routine, mas não substituem a leitura.
