# Jurídico Municipal – Radar de credores dos municípios do Ceará

Sistema para escritório jurídico que localiza **fornecedores e prestadores de serviço com
débitos em aberto há mais de 11 meses** nos 184 municípios do Ceará, a partir dos dados
que as próprias prefeituras enviam ao **TCE-CE pelo SIM** (Sistema de Informações Municipais).

Para cada credor, o sistema entrega:

* quanto está **liquidado e não pago** (serviço entregue e atestado, art. 63 da Lei 4.320/64);
* quanto está **empenhado e não liquidado** (opcional);
* desde quando cada valor está em aberto;
* quais municípios devem e quais empenhos compõem a dívida;
* alertas de **cancelamento de resto a pagar processado**, despesa do **fim de mandato
  (art. 42 da LRF)** e **possível prescrição**;
* um **dossiê** com os fundamentos para a cobrança e os documentos a reunir.

## Fonte dos dados

[API de Dados Abertos do SIM – TCE-CE](https://api-dados-abertos.tce.ce.gov.br/sim/)
(documentação em OpenAPI). É a mesma informação contábil exibida nos portais da transparência
municipais, reunida num só lugar e num formato padronizado para todos os 184 municípios.

| Tabela do SIM | Uso |
|---|---|
| `notas_empenhos` | credor (nome, CNPJ, endereço), elemento de despesa, valor empenhado, histórico, contrato |
| `liquidacoes` | datas e valores liquidados (ignora as estornadas) |
| `notas_pagamentos` | datas e valores pagos (ignora os estornados) |
| `notas_anulacoes_empenhos` | anulações e cancelamentos de restos a pagar |

Liquidações, pagamentos e cancelamentos de restos a pagar ficam no exercício do empenho,
com mês de referência dos anos seguintes. Por isso o sistema consulta, para cada exercício,
todos os meses até hoje.

> A API aceita apenas acessos de IPs do Brasil.

## Instalação

Precisa de Python 3.10 ou superior. O `openpyxl` é opcional e serve para gerar a planilha Excel.

```bash
git clone https://github.com/juridicofernandalobo-maker/JURIDICO-MUNICIPAL.git
```

```bash
cd JURIDICO-MUNICIPAL
```

```bash
pip install openpyxl
```

## Uso

Lista os municípios e seus códigos no TCE-CE:

```bash
python -m juridico_municipal municipios
```

Busca em alguns municípios. O padrão analisa os empenhos dos últimos 5 exercícios e do atual:

```bash
python -m juridico_municipal buscar --municipios "SOBRAL,IGUATU,JUAZEIRO DO NORTE"
```

Busca no estado inteiro. São cerca de 650 consultas por município; a primeira execução leva
algumas horas, e as seguintes aproveitam o cache em `.cache/`:

```bash
python -m juridico_municipal buscar --todos
```

Principais opções:

| Opção | Padrão | Efeito |
|---|---|---|
| `--meses N` | 11 | atraso mínimo em meses |
| `--anos 2021-2025` | últimos 5 + atual | exercícios dos empenhos analisados |
| `--valor-minimo V` | 1000 | total mínimo por credor |
| `--nao-processados` | não | inclui empenhado e não liquidado |
| `--pessoa-fisica` | não | inclui credores pessoas físicas (CPF vem cifrado pelo TCE) |
| `--todos-elementos` | não | não filtra por elemento de despesa |
| `--data-base AAAA-MM-DD` | hoje | data de referência do atraso |
| `--saida PASTA` | `saida` | onde gravar os relatórios |
| `--workers N` | 16 | consultas simultâneas à API |

## Ver o painel

O sistema não fica no ar como um site: ele gera os relatórios em HTML na pasta `saida/`.
Para abrir o painel no navegador:

```bash
python -m juridico_municipal servir
```

O endereço é `http://localhost:8000/painel.html`. No computador, também dá para abrir o
arquivo `saida/painel.html` com dois cliques.

### No GitHub Codespaces (VS Code no navegador)

1. No repositório, clique em **Code > Codespaces > Create codespace on main**. A configuração
   em `.devcontainer/` já instala o necessário.
2. No terminal do Codespace, gere os relatórios e abra o painel:

```bash
python -m juridico_municipal buscar --municipios IGUATU
```

```bash
python -m juridico_municipal servir
```

3. Abra a aba **PORTAS** (Ports), localize a porta **8000** ("Painel do radar") e clique no ícone
   do globo. O próprio comando também mostra o link direto.

> Se aparecer uma tela do **Jupyter pedindo token ou senha**, você abriu a porta errada
> (8888, do Jupyter). Feche essa tela e use a porta **8000**. O sistema não usa Jupyter.

> Se aparecer **401 Unauthorized** (página em branco), o túnel do GitHub não reconheceu o
> seu login. A porta é privada e só abre para a conta dona do Codespace. Tente, nesta ordem:
>
> 1. Abra pelo ícone do globo na aba **PORTAS**, e não colando o link. Esse clique faz a
>    autenticação.
> 2. Use uma janela normal do navegador, não anônima, logada na mesma conta do GitHub. Em
>    Configurações > Privacidade > Cookies de terceiros, permita os sites
>    `[*.]github.dev` e `[*.]app.github.dev`.
> 3. Abra dentro do próprio VS Code: `Ctrl+Shift+P` > **Simple Browser: Show** e cole
>    `http://localhost:8000`.
> 4. Sem servidor: clique com o botão direito em `saida/painel.html` > **Download** e abra o
>    arquivo no computador. Para os dossiês, baixe a pasta `saida` inteira.
>
> Evite tornar a porta pública: qualquer pessoa com o link veria o painel.

## Saídas (pasta `saida/`)

| Arquivo | Conteúdo |
|---|---|
| `painel.html` | painel com busca por nome/CNPJ, filtro por município e prioridade, ordenação por coluna |
| `dossies/*.html` | dossiê por credor: empenhos, valores, alertas, fundamentos, checklist e caminhos de cobrança |
| `radar_credores.xlsx` | abas Credores, Débitos por empenho e Municípios |
| `credores.csv` | um credor por linha, com prioridade A/B/C |
| `debitos_por_empenho.csv` | um empenho em aberto por linha |
| `municipios.csv` | total em aberto por município e último mês enviado ao SIM |

**Prioridade:** A para liquidado e não pago ≥ R$ 100 mil, ou ≥ R$ 30 mil com atraso ≥ 24 meses;
B para ≥ R$ 20 mil; C para os demais.

## Como o débito é apurado

Para cada nota de empenho:

```
saldo processado     = liquidado − pago
saldo não processado = empenhado − anulado − liquidado
```

* **Idade do débito:** conta da liquidação mais antiga ainda não paga. Os pagamentos quitam
  as liquidações em ordem cronológica (art. 141 da Lei 14.133/21).
* **Corte:** entra no radar o débito cuja data-base é anterior a *hoje − 11 meses*.
* **Credores considerados:** pessoas jurídicas (CNPJ) nos elementos típicos de fornecedores e
  prestadores: 30, 31, 32, 33, 35, 36, 37, 39, 40, 51, 52 e 92.
* **Credores excluídos:** folha, INSS, Receita Federal, fundos, órgãos públicos, consórcios
  públicos e sindicatos.

Duas conciliações evitam apontar como dívida o que já foi pago:

1. **Pagamento lançado em outro empenho do mesmo credor.** É comum o município liquidar num
   empenho e pagar em outro. O que foi pago acima do liquidado num empenho abate os débitos
   abertos do mesmo credor, no mesmo exercício ou em exercícios anteriores.
2. **Relançamento, DEA ou reconhecimento de dívida.** Quando o resto a pagar é cancelado e
   reempenhado no ano seguinte (histórico com "relançamento", "exercício anterior",
   "reconhecimento de dívida" ou elemento 92), o novo empenho abate o antigo do mesmo credor.
   Primeiro abate o empenho cujo número aparece no histórico, depois os mais antigos.

Os dois abatimentos aparecem como alerta no dossiê, para conferência.

### Limites

* O SIM mostra **o que o município informou** ao TCE-CE. Antes de qualquer providência,
  confirme cada empenho no portal da transparência do município e com o próprio credor.
  Os endereços dos portais podem ser cadastrados em
  `juridico_municipal/dados/portais_transparencia.csv` e aparecem nos dossiês.
* Município com envio do SIM atrasado aparece com ⚠️ no painel: pagamentos recentes podem
  ainda não constar.
* As conciliações são conservadoras: podem esconder alguma dívida verdadeira, mas evitam
  apontar como devido o que já foi pago.
* Os valores são nominais, sem correção monetária e sem juros.

## Fundamentos usados nos dossiês

* Lei 4.320/64, arts. 36, 37 e 58 a 64: empenho, liquidação, pagamento, restos a pagar e
  despesas de exercícios anteriores.
* Lei 14.133/21: art. 141 (ordem cronológica), art. 137, § 2º, IV, e § 3º, II (atraso superior
  a 2 meses) e art. 92, V (atualização financeira).
* Lei 8.666/93, art. 78, XV, para contratos regidos pela lei antiga.
* Decreto 20.910/32: prescrição quinquenal e suspensão pelo requerimento administrativo.
* Súmula 339/STJ: ação monitória contra a Fazenda Pública.
* CF, art. 100: precatório e RPV.
* LRF, art. 42: obrigações contraídas nos dois últimos quadrimestres do mandato.

## Ética profissional e LGPD

A abordagem de potenciais clientes deve observar o Código de Ética e Disciplina da OAB
(art. 7º e arts. 39 a 47 – vedação à captação de clientela e à mercantilização) e o
Provimento 205/2021 do CFOAB (publicidade informativa e sóbria). Os dados são públicos
(Lei 12.527/2011), mas o tratamento deve respeitar a LGPD, especialmente para credores
pessoas físicas. Por isso o sistema não inclui pessoas físicas por padrão.

## Testes

```bash
python -m pytest -q
```
