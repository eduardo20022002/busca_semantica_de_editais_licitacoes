# Perfil Aurora V4: revisão completa a partir do conteúdo colado do site oficial

O usuário colou o texto integral da página de soluções do site institucional (extraído manualmente do navegador) e pediu uma revisão do zero das 4 categorias com correspondência direta no site (`cloud-para-saude`, `software-de-gestao-em-saude`, `telessaude`, `interoperabilidade-em-saude`), descartando a análise da ADR-0003 como ponto de partida mas reaplicando os mesmos cuidados já validados: não copiar bullets de marketing orientados a benefício ("Redução do tempo de espera", "Mais visibilidade sobre indicadores") e não reintroduzir o termo "medicamentos"/MAT-MED em `software-de-gestao-em-saude`, que já causou uma regressão real (91% do top-100 dominado por editais de compra pura de remédio, ver ADR-0003).

`ia-para-saude`, `ciberseguranca-em-saude` e `dispositivos-medicos-conectados-iot` foram mantidos sem alteração — o texto colado do site não cobre essas 3 categorias (elas continuam no Escopo Aurora por decisão de negócio já registrada na ADR-0003, não por estarem no site).

Duas seções do site não têm categoria própria no Escopo Aurora (`CONTEXT.md`) e foram absorvidas em categorias existentes, mantendo a decisão da ADR-0003 de não expandir o Escopo:

- **Consultoria Digital em Saúde** ("Diagnóstico de maturidade digital", "Planejamento estratégico de TI") → dobrada em `software-de-gestao-em-saude`, por ser instrumental à implantação de sistemas de gestão hospitalar, não uma categoria de TI em saúde por si só.
- **Aurora Real-Time** ("Monitoramento de indicadores críticos", "Identificação de gargalos operacionais", "Otimização de recursos assistenciais") → dobrada em `software-de-gestao-em-saude`, já que `CONTEXT.md` define essa categoria como cobrindo "gestão de leitos/agenda/faturamento em saúde".

**Módulos Complementares** (acessibilidade, laboratório, recrutamento, por menção na ADR-0003) não foi coberta nesta revisão — o texto colado pelo usuário trazia só o link de navegação para essa seção, sem o conteúdo do corpo da página.
