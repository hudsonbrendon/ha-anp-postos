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

O aviso não se repete enquanto o posto continuar igual.

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
