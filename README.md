# Monitor de Verbas Públicas Municipais & Medicamentos da Rede Pública (Agent Spec)

Especificação completa de Agente de Inteligência Artificial (`agent.md` / `agents.md`) especializado em **governo digital, finanças públicas brasileiras e políticas de assistência farmacêutica do Sistema Único de Saúde (SUS)**.

Este projeto define as instruções comportamentais, metodologias de consulta e diretrizes de conformidade para que modelos de IA atuem como auditores e analistas de dados públicos, organizando repasses federais e estaduais para municípios brasileiros e detalhando a distribuição de medicamentos por esfera de responsabilidade.

---

## 🎯 Objetivo do Projeto

O objetivo desta especificação é capacitar assistentes e agentes autônomos a:
1. **Rastrear e auditar repasses financeiros:** Localizar receitas transferidas pela União e pelos Estados aos municípios (FPM, FUNDEB, SUS, FNAS, Emendas Parlamentares, ICMS, IPVA, Royalties, etc.).
2. **Classificar a regularidade de repasses:** Avaliar se as transferências estão *Em dia*, *Pendentes/Não realizadas* ou em situação *Indeterminada*, confrontando previsões com arrecadações e cronogramas oficiais.
3. **Mapear a Assistência Farmacêutica (SUS):** Estruturar o fornecimento de medicamentos da rede pública separando-os didaticamente por esferas e componentes (Componente Básico, Especializado e Estratégico).
4. **Democratizar a transparência pública:** Traduzir termos técnicos orçamentários (ex.: *repasses fundo a fundo*, *dedução do FUNDEB*, *RCL*, *LME*) para uma linguagem clara e acessível a qualquer cidadão.

---

## 🏛️ Fontes de Dados Oficiais Homologadas

O agente opera **exclusivamente com dados oficiais de portais e APIs públicas**, seguindo a ordem de prioridade:

| Ordem | Fonte / Plataforma | Abrangência / Finalidade |
|:---:|---|---|
| **1º** | **Portal da Transparência do Governo Federal** | Transferências diretas, emendas parlamentares e convênios |
| **2º** | **Fundo Nacional de Saúde (FNS)** | Repasses Fundo a Fundo e blocos de custeio/investimento do SUS |
| **3º** | **Sistema Siconfi (Secretaria do Tesouro Nacional)** | DCA (Contas Anuais), RREO (Execução Orçamentária) e RGF (Gestão Fiscal) |
| **4º** | **Transferegov.br / Siconv** | Convênios, instrumentos de repasse e contratos de obras |
| **5º** | **Fundo Nacional de Desenvolvimento da Educação (FNDE)** | Repasses do Salário-Educação, PNAE (Merenda), PNATE (Transporte) e PDDE |
| **6º** | **Tribunais de Contas (TCEs) e Portais Estaduais** | Cotas-partes de impostos estaduais (ICMS, IPVA) e auditorias de despesa |
| **7º** | **RENAME e REMUME (Ministério da Saúde / Municípios)** | Componentes da Assistência Farmacêutica e Protocolos Clínicos (PCDT) |

> ⚠️ **Aviso de Integridade:** O agente é estritamente proibido de utilizar especulações, opiniões de imprensa ou inventar dados numéricos. Quando uma fonte oficial não dispuser do dado ou estiver desatualizada, a restrição é informada explicitamente.

---

## 📊 Regras de Classificação e Metodologia

### 1. Status de Repasses
Cada transferência pública analisada deve receber uma das seguintes classificações:
* 🟢 **Em dia (positivo):** O repasse ocorreu dentro do prazo previsto, ou os demonstrativos do encerramento orçamentário confirmam pagamento/arrecadação integral concluída.
* 🔴 **Pendente ou não realizado (negativo):** O prazo legal previsto expirou sem registro de crédito bancário, ou a fonte aponta cancelamento/suspensão por inadimplência.
* 🟡 **Indeterminado:** A fonte oficial consultada não possui cronograma prévio para comparação ou apresenta registros parciais/incompletos. O motivo da indeterminação é sempre justificado.

### 2. Divisão da Assistência Farmacêutica
Os medicamentos são categorizados estritamente pelas três esferas de pactuação do SUS:
* **Esfera Municipal (Componente Básico – CBAF / REMUME):** Medicamentos essenciais da Atenção Primária (hipertensão, diabetes, antibióticos, analgésicos), dispensados nas Unidades Básicas de Saúde (UBSs) e Farmácias Municipais.
* **Esfera Estadual (Componente Especializado – CEAF / "Alto Custo"):** Medicamentos de alta complexidade e custo elevado (biológicos, imunossupressores, doenças raras/crônicas), regulados por LME (Laudo de Solicitação) e PCDT.
* **Esfera Federal (Componente Estratégico – CESAF):** Medicamentos adquiridos centralizadamente pelo Ministério da Saúde para programas de controle de endemias e perfis epidemiológicos (Tuberculose, Hanseníase, HIV/AIDS, Malária, vacinas do PNI).

---

## 📁 Estrutura do Repositório

```text
├── agent.md             # Especificação e prompt de sistema do agente (versão padrão)
├── agents.md            # Regra de projeto para o ambiente Antigravity / Gemini CLI
├── transfers_sb.csv     # Amostra de dados brutos extraídos (exercício 2024 de Santa Bárbara d'Oeste - SP)
└── README.md            # Documentação e guia de uso do projeto
```

---

## 🚀 Como Usar Este Projeto

### 1. Com o Google Antigravity / Gemini CLI
Basta clonar este repositório no seu diretório de trabalho ou apontar para a pasta do projeto. O assistente carregará automaticamente o arquivo `AGENTS.md` como diretriz hierárquica comportamental permanente:

```bash
git clone https://github.com/fusca75/agent-spec.git
cd agent-spec
```

### 2. Com outros Agentes e Modelos de Linguagem (Claude, ChatGPT, etc.)
Você pode copiar o conteúdo integral de [`agent.md`](agent.md) e colá-lo como **Prompt de Sistema (System Prompt)** ou como **Instruções Personalizadas (Custom Instructions)** da sua ferramenta.

### 3. Exemplos de Consultas Suportadas
* *"Quais foram os repasses federais da saúde para o município de Santa Bárbara d'Oeste em 2024?"*
* *"Qual o percentual que a cidade X aplicou em educação básica pelo FUNDEB no último ano?"*
* *"Como funciona a retirada de remédios para artrite reumatoide pelo SUS na minha cidade?"*
* *"Compare os indicadores fiscais e gastos em saúde entre a cidade A e a cidade B."*

---

## 🛡️ Ética, Transparência e LGPD

* **Privacidade e LGPD:** O agente opera unicamente com dados públicos e agregados de finanças municipais. Jamais são expostos dados pessoais sensíveis ou identificadores individuais de munícipes e pacientes.
* **Neutralidade Absoluta:** O agente mantém postura estritamente técnica, analítica e imparcial, sem emissão de juízos de valor político-partidários sobre governantes ou administrações.
* **Validação Prévia:** Todas as análises orientam o cidadão a validar dados nos portais locais antes de qualquer tomada de decisão jurídica, administrativa ou formalização de denúncia a órgãos de controle externo.

---

## 📄 Licença

Este projeto é disponibilizado sob a licença [MIT](https://opensource.org/licenses/MIT). Sinta-se livre para utilizar, adaptar e expandir esta especificação para aprimorar o controle social e a transparência pública no Brasil.
