<p align="center"><img src="logo.png" alt="ANP Postos" height="120"></p>

# ANP Postos para Home Assistant

Coloca no mapa do Home Assistant os postos de combustível autorizados pela ANP nas cidades que você escolher, com a **nota da ANP (0 a 5)**, fiscalizações, infrações, amostras de combustível e interdições, e **avisa quando um posto fica irregular**.

Os dados vêm do [ANP Com Vc - Postos](https://anpcomvcpostos.anp.gov.br/), o app oficial da Agência Nacional do Petróleo. Ele não tem API pública: a integração reproduz o fluxo do próprio site (veja [REVERSE_ENGINEERING.md](REVERSE_ENGINEERING.md)).

## O que aparece

**Um `geo_location` por posto** (estado = distância de casa em km), com marcador colorido pela nota no mapa:

| Atributo | Exemplo |
|---|---|
| `nota` | `2` (0 a 5, cores do site) |
| `irregular` | `true` |
| `razao_social`, `nome`, `cnpj_formatado` | `POSTO DA TAMARINEIRA LTDA` |
| `distribuidora`, `distribuidora_desde`, `status_recebimento`, `volume_outras_distribuidoras_pct` | `VIBRA ENERGIA S.A` |
| `endereco`, `complemento`, `bairro`, `cep`, `municipio`, `uf`, `link_mapa` | |
| `situacao`, `interditado`, `motivo_interdicao`, `tipo` | `EM OPERAÇÃO` |
| `fiscalizacoes`, `fiscalizacoes_com_infracao`, `fiscalizacoes_sem_infracao` | `5`, `1`, `4` |
| `infracoes`, `infracoes_qualidade`, `infracoes_quantidade` | `3`, `3`, `0` |
| `amostras`, `amostras_conformes`, `amostras_nao_conformes` | `15`, `14`, `1` |
| `autorizacao`, `numero_despacho`, `portaria_resolucao`, `numero_processo`, `dou_envio`, `dou_publicacao`, `tempo_autorizacao_anos` | |

Para postos irregulares a integração busca também (opcional): **histórico de fiscalizações**, **irregularidades** (auto de infração, classificação, descrição), **ensaios não conformes** (ex.: teor de etanol 30%), **produtos vendidos** e **origem do combustível** (de quais distribuidoras o posto recebeu).

**Um dispositivo por cidade** com os sensores: Postos, Postos irregulares (lista nos atributos), Nota média (distribuição por nota e melhores postos), Postos interditados, Infrações e Amostras não conformes.

## Avisos de posto irregular

Irregular = nota até o limite escolhido (padrão 2), interditado ou fora de operação. Quando um posto entra nessa lista (ou a nota cai), a integração:

- cria uma notificação persistente com nota, endereço, infrações e link do mapa;
- envia pelos serviços `notify.*` escolhidos (ex.: app do celular, com clique abrindo o mapa);
- dispara o evento `anp_postos_posto_irregular` com todos os dados, para automações.

O aviso não se repete enquanto o posto continuar igual. Se a ANP estiver fora do ar ou limitar as requisições (HTTP 429), a integração usa o último dado salvo.

## Aviso ao chegar no posto

Escolha nas opções os celulares (app do Home Assistant) que devem receber o aviso. Quando um deles chega a até 120 m (ajustável) de um posto das cidades monitoradas, só aquele celular recebe um push:

| Veredito | Quando |
|---|---|
| ✅ **Pode abastecer** | nota 4–5 sem infrações nos últimos 5 anos |
| ⚠️ **Abasteça com atenção** | nota logo acima do limite, ou nota < 5 com infração registrada |
| ⛔ **Não abasteça aqui** | irregular: nota até o limite, interditado ou fora de operação (push *time-sensitive* no iPhone) |
| ❔ **Sem nota** | a ANP não calculou nota |

O push traz nota, distribuidora, fiscalizações, infrações, amostras reprovadas, motivo da interdição e as últimas irregularidades; tocar abre o posto no app. Mesmo posto e mesmo celular: no máximo um aviso a cada 3 h. O evento `anp_postos_chegada` (tracker, veredito, distância, CNPJ, posto, nota, entity_id) permite montar automações próprias.

Como o app do iPhone só manda localização a cada ~500 m em segundo plano, quando o celular passa a menos de 700 m de um posto a integração pede uma posição nova ao app (`request_location_update`, no máximo a cada 10 min), para pegar o momento da parada. Para mais precisão, deixe a localização do app em "Sempre" com localização precisa ativada.

## Instalação

HACS → Repositórios personalizados → `https://github.com/hudsonbrendon/ha-anp-postos` (Integração) → instalar → reiniciar. Depois **Configurações → Dispositivos e serviços → Adicionar integração → ANP Postos** e escolha as cidades. Para trocar cidades, limite ou notificações: **Configurar** na integração.

## Mapa

```yaml
type: map
geo_location_sources:
  - anp_postos
hours_to_show: 0
default_zoom: 13
```

Para ver só os irregulares, use um card de mapa com `entities:` filtradas (ex.: auto-entities por `attributes.irregular: true`).

## Como a nota é calculada (segundo a ANP)

`Nota = 5 − arredondar(2 × infrações 0–2 anos + 1 × infrações 2–5 anos + 1 × amostras NC 0–2 anos + 0,5 × amostras NC 2–5 anos)`. Nota zero para posto inativo, interditado totalmente ou desconto maior que 5. Por decisão liminar (FECOMBUSTÍVEIS), amostras não conformes do PMQC estão temporariamente fora do cálculo.
