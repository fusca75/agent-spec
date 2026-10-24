# Transparência municipal

Dashboard local para consultar registros financeiros e transferências públicas de municípios brasileiros. A página usa o código oficial do município no IBGE, consulta dados abertos do Tesouro Nacional (Siconfi) e, quando há chave configurada, consulta registros do Portal da Transparência. A RENAME é apresentada como referência oficial de medicamentos do SUS.

## Iniciar

Na pasta do projeto, execute:

```powershell
python servidor_dashboard.py
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000). A lupa pesquisa a lista nacional de municípios do IBGE. Ao escolher uma cidade, a dashboard exibe primeiro o cache daquela cidade, se existir, e inicia uma nova consulta oficial.

Os dados são atualizados ao abrir a página, ao trocar de município, pelo botão **Atualizar agora**, ao voltar para a aba e a cada 15 minutos enquanto ela estiver visível. Isso atualiza a consulta; a data de publicação de cada base depende do órgão responsável e pode ser anterior ao dia da consulta. A tela separa o horário da consulta da data ou período a que o dado se refere.

O servidor grava consultas em `data/municipios/<código-IBGE>.json`. Se uma fonte não retornar linhas novas, dados municipais previamente consultados podem ser reaproveitados; a página indica esse uso e conserva a referência original de cada linha. Dados de municípios ainda não consultados não são inventados nem preenchidos com a amostra histórica de outra cidade.

## Fontes, limites e atualização

- **IBGE Localidades:** identifica municípios e códigos IBGE; não fornece valores de repasses.
- **Siconfi / Tesouro Nacional:** fornece RREO, extrato de entregas e DCA. O RREO é uma demonstração periódica, não um fluxo de pagamentos em tempo real. O painel procura o último período publicado e apresenta o exercício/período.
- **Portal da Transparência:** oferece consultas de convênios, despesas e programas federais. A API exige cadastro e token. Para habilitar as consultas do coletor, configure `PT_API_KEY` como variável de ambiente antes de iniciar o servidor. Sem a chave, a tela informa a limitação e mantém os dados públicos acessíveis pelo Siconfi.
- **RENAME / Ministério da Saúde:** a seção de medicamentos direciona à edição oficial e à ferramenta de consulta do Ministério da Saúde. A presença na RENAME não confirma estoque ou disponibilidade em uma unidade de saúde municipal.

O Siconfi limita o uso da API a uma requisição por segundo. Uma consulta pode demorar enquanto procura o último demonstrativo disponível. A tela mantém o cache à vista durante esse processo.

## Escopo das APIs indicadas no `agents.md`

As URLs entregues foram avaliadas conforme sua finalidade. O catálogo do dados.gov.br descreve conjuntos de dados; a API COFIEX se refere a projetos com financiamento externo e garantia da União; os endpoints do CADE tratam de atos de concentração e consultas por protocolo/documento; o endpoint ConectaGov fornece autenticação; e o eAUD é um sistema de auditoria com acesso próprio. Esses serviços não são fontes gerais de pagamentos municipais abertas para esta dashboard. Os endpoints que consultam CPF/CNPJ não são utilizados.

## Status e interpretação

- **Em dia / positivo:** usado somente se a fonte trouxer evidência suficiente de pagamento no prazo.
- **Pendente / negativo:** usado para situações explicitamente suspensas, canceladas ou rescindidas na fonte.
- **Indeterminado:** usado quando a base mostra valores, execução, vigência ou ausência de registros, mas não oferece um calendário de pagamento que permita verificar pontualidade.

O RREO apresenta previsão e realização orçamentárias agregadas, e não cronogramas individuais de repasse. Por isso, comparação entre esses valores, isoladamente, não comprova atraso nem pagamento no prazo.

## Arquivos principais

- `dashboard_repasses.html`: interface, busca de municípios, cache em tela, exportação CSV e atualização periódica.
- `servidor_dashboard.py`: servidor local, endpoint de cache por município e endpoint de atualização.
- `coletor_vivo.py`: integração com IBGE, Siconfi e Portal da Transparência.
- `data/municipios/`: cache de consultas por código IBGE.

As informações são agregadas e destinam-se à consulta pública. Valide dados críticos diretamente nas fontes oficiais antes de tomar decisões ou registrar denúncias.

## Publicar no Render

O repositório inclui um Blueprint em `render.yaml`. Ele cria um Web Service Python, usa a porta `PORT` fornecida pelo Render, escuta em `0.0.0.0` e verifica a rota `/healthz`. Os dados consultados são cache local temporário: no plano Free, o sistema de arquivos é efêmero e o serviço pode suspender após 15 minutos sem tráfego; após reinício ou suspensão, a primeira consulta pode demorar enquanto busca as fontes oficiais. Para persistir esse cache num plano pago, conecte um disco em `/var/data` e configure `DASHBOARD_DATA_DIR=/var/data` nas variáveis do serviço. Outra opção é substituir o cache por um banco/serviço de armazenamento.

Passos pelo painel:

1. Abra o [Render Dashboard](https://dashboard.render.com/) e escolha **New > Blueprint**.
2. Conecte sua conta GitHub, se ainda não estiver conectada, e selecione `fusca75/agent-spec`.
3. Escolha a branch `main` e o arquivo Blueprint `render.yaml` na raiz do repositório.
4. Revise o Web Service `transparencia-municipal` e selecione **Deploy Blueprint**.
5. Acompanhe o primeiro build e deploy nos logs do serviço. Quando ficar **Live**, abra a URL `*.onrender.com` exibida no painel.
6. Opcional: para habilitar os registros do Portal da Transparência, obtenha uma chave na página de cadastro da API. No serviço do Render, abra **Environment > Add Environment Variable**, cadastre `PT_API_KEY` com a chave, salve e faça o redeploy. Não coloque a chave em `render.yaml`, no HTML ou no GitHub.

Para cache persistente (opcional e em plano pago): na página do serviço, crie um Persistent Disk montado em `/var/data` e adicione `DASHBOARD_DATA_DIR=/var/data` nas variáveis de ambiente. O plano Free não oferece disco persistente.

O deploy automático está configurado para cada commit enviado à `main`. O Render exige que Web Services escutem em `0.0.0.0` e na porta indicada por `PORT`; as variáveis de ambiente são o local apropriado para credenciais. [Web Services](https://render.com/docs/web-services) · [Blueprints](https://render.com/docs/blueprint-spec) · [Variáveis e segredos](https://render.com/docs/configure-environment-variables) · [Limitações do plano Free](https://render.com/docs/free)
