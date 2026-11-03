# Engenharia reversa: ANP Com Vc - Postos

Site: <https://anpcomvcpostos.anp.gov.br/> (visto no reel @jornadatop, 01/11/2026).
Ferramentas: REA (cenário de browser + análise do bundle APEX), browser-harness no Chrome, Python.

## Stack

- Oracle APEX 24.2.13 sobre ORDS (`/ordsdw/`), app **204** (`anpcomvcpostos`), tema Universal 42.
- Cloudflare na frente; Dynatrace RUM (`ruxitagentjs`, `rb_*`) — irrelevante.
- Mapa: região *Map* do APEX (`widget.spatialMap`, MapLibre, tiles `elocation.oracle.com`).
- Sem API REST/ORDS pública para os dados: tudo passa pelo protocolo AJAX do APEX.

## Sessão

`GET /ordsdw/r/sfi_apex/anpcomvcpostos/home` cria a sessão: cookie `ORA_WWV_APP_204` (path `/ordsdw/`) + `p_instance` no HTML.
Todos os `ajaxIdentifier` e checksums (`cs=`, `pPageItemsProtected`) são **amarrados à sessão** — reaproveitar de outra sessão devolve a home em HTML (sem erro JSON). URLs de página sem `cs` válido devolvem 400.

Hidden inputs úteis da página: `pInstance`, `pFlowStepId`, `pContext`, `pSalt`, `pPageSubmissionId`, `pPageItemsProtected`.

## Páginas

| Alias | Página | Conteúdo |
|---|---|---|
| `home` | 1 | `P1_CIDADE` (select com **5594** cidades, `value` = id interno), `P1_CNPJ`, botões |
| `postos-lista` | 5 | Interactive Grid `R38277306105099103`, 42 colunas |
| `postos-mapa` | 6 | Map region `R38754807153732992`, camadas Nota 0..5 |
| `postos-mapa-posicao` | 15 | postos próximos da geolocalização |
| `posto-geral` | 8 | resumo do posto + botões para as abaixo |
| `posto-detalhe` | 9 | cadastro + IG de produtos |
| `fiscalizacoes` | 10 | IG fiscalizações (DF, data, órgão, infração S/N) + IG irregularidades |
| `amostras` | 11 | IG amostras PMQC (data, produto, conforme) + IG ensaios não conformes |
| `origem-combustivel` | 12 | relatório clássico: distribuidora → % do volume (6 meses) |
| `nota` | 2 | diálogo com a fórmula da nota |

## Fluxo "Listar Postos da cidade"

1. **Dynamic Action PL/SQL** no change de `P1_CIDADE` (procurar `"attribute01":"#P1_CIDADE"` para o `ajaxIdentifier`):

   ```
   POST /ordsdw/wwv_flow.ajax?p_context=anpcomvcpostos/home/<inst>
   p_flow_id=204&p_flow_step_id=1&p_instance=<inst>&p_debug=
   p_request=PLUGIN=<ajaxIdentifier>
   p_json={"pageItems":{"itemsToSubmit":[{"n":"P1_CIDADE","v":"7221"}],"protected":"<pPageItemsProtected>","rowVersion":""},"salt":"<pSalt>"}
   → {"item":[{"id":"P1_MUNICIPIO","value":"NATAL"},{"id":"P1_UF","value":"RN"}]}
   ```

2. **Submit** (`apex.submit({request:'busca_cidade_lista'})`, `pReloadOnSubmit=S` = AJAX; precisa `X-Requested-With: XMLHttpRequest`, senão volta HTML):

   ```
   POST /ordsdw/wwv_flow.accept?p_context=anpcomvcpostos/home/<inst>
   p_request=busca_cidade_lista&p_reload_on_submit=S&p_page_submission_id=<...>
   p_json={"pageItems":{"itemsToSubmit":[P1_CIDADE_BUSCA,P1_CIDADE,P1_CNPJ,P1_MUNICIPIO,P1_UF],"protected":...,"rowVersion":"","formRegionChecksums":[]},"salt":...}
   → {"redirectURL":"/ordsdw/r/sfi_apex/anpcomvcpostos/postos-lista?p5_municipio=NATAL&p5_uf=RN&clear=1&session=...&cs=..."}
   ```

   (`busca_cidade_MAPA` leva à página 6 com o mesmo filtro.)

3. **postos-lista**: as 25 primeiras linhas vêm em `var gIg38277306105099103data = {...}` (`values`, `moreData`, `totalRows`). A ordem dos valores segue `config.columns` do IG; o último item de cada linha é metadado com `fields.CNPJ.url` (URL assinada do `posto-geral`).

4. **Restante do IG** (`modelViewBase` → `apex.server.plugin`):

   ```
   POST /ordsdw/wwv_flow.ajax?p_context=anpcomvcpostos/postos-lista/<inst>
   p_flow_id=204&p_flow_step_id=5&p_instance=<inst>
   p_json={"regions":[{"id":"38277306105099103","ajaxIdentifier":"...","ajaxColumns":"...","reportId":"<savedReports[0].id>","view":"grid","fetchData":{"version":1,"firstRow":1,"maxRows":10000}}],"salt":"..."}
   → {"regions":[{"fetchedData":{"values":[...],"moreData":false,"totalRows":106}}]}
   ```

### Colunas do IG de postos

`COD_INSTALACAO, CNPJ, CNPJ_TXT, RAZAO_SOCIAL, NOME, DISTRIBUIDORA, DISTRIBUIDORA_DATA_INICIO, PARTICIAPCAO_DITRIBUIDORA_PERC, STATUS_RECEBIMENTO, POSTO_TIPO, INTERDITADO, SITUACAO_ATUAL, SITUACAO_CORRIGIDA, ENDERECO, COMPLEMENTO, BAIRRO, CEP, MUNICIPIO, UF, LATITUDE, LONGITUDE, AUTORIZACAO, NUMERO_DESPACHO, PORTARIA_RESOLUCAO, N_PROCESSO, DOU_DATA_ENVIO, DOU_DATA_PUBLICACAO, FISCALIZACOES_TOTAL, FISCALIZACOES_SEM_INFRACAO, FISCALIZACOES_COM_INFRACAO, INFRACAO_QUALIDADE, INFRACAO_QUANTIDADE, INFRACAO_TOTAL, AMOSTRAS_TOTAL, AMOSTRAS_NC, AMOSTRAS_CONFORME, ORDEM, LAT_NUM, LON_NUM, NOTA, MOTIVO_INTERDICAO, TEMPO_AUTORIZACAO_ANOS`

Números em pt-BR (`"-05,76872790"`, `"5,043"`), datas `d/m/aaaa`.

## Mapa (página 6)

`spatialMap` com `lazyLoading:true`; os pontos vêm de `wwv_flow.ajax` com `p_request=PLUGIN=<ajaxIdentifier>&x01=GET_FEATURES&x02={"bbox":[...],"zoom":n}`. Camadas `_` + `Nota 0..5`, cores `#f5a3a3 #ff9a4d #ffe066 #9ad800 #1faf5b #084c2e`. Tooltip: CNPJ, razão social, distribuidora, endereço, tempo de operação, nota, interditado. O IG da lista tem tudo isso e mais, então a integração usa a lista.

## Detalhe do posto

`posto-geral` tem os links (assinados) via `apex.navigation.redirect('...')` para `fiscalizacoes?p10_cod_instalacao=..&p10_cnpj=..`, `amostras?p11_...`, `posto-detalhe?p9_...`, `origem-combustivel?p12_...` e o diálogo `nota`. Cada uma traz IGs embutidos (`gIg<region>data`) cujos nomes de coluna são frases ("Número do Documento de Fiscalização"), por isso a leitura é posicional. Os dados cobrem os últimos 5 anos (fiscalizações/amostras) e 6 meses (origem).

## Nota

`5 − round(2·infr(0–2a) + 1·infr(2–5a) + 1·amostrasNC(0–2a) + 0,5·amostrasNC(2–5a))`; zero para inativo, interditado total ou desconto > 5. Amostras NC do PMQC suspensas do cálculo por liminar (FECOMBUSTÍVEIS).
