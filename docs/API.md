# Contrato da API ENADE Search (integração com o frontend)

Documentação interativa (sempre atualizada, gerada do código): **http://localhost:8001/docs**
(Swagger) e http://localhost:8001/redoc. Este arquivo resume o contrato. Exemplos JSON reais,
gerados pela própria API, estão em [`api/exemplos/`](../api/exemplos) e servem de dados simulados.

O frontend consome **somente** esta API. Ele não precisa conhecer Elasticsearch, Redis, Kafka ou LDAP.

## Endpoints disponíveis

| Método | Rota | Autenticação | Descrição |
|---|---|---|---|
| GET | `/` | pública | API online |
| GET | `/api/health` | pública | status de API, Elasticsearch e Redis |
| POST | `/api/auth/login` | pública | login LDAP → token |
| GET | `/api/auth/me` | qualquer perfil | usuário e permissões da sessão |
| POST | `/api/auth/logout` | qualquer perfil | encerra sessão e apaga o carrinho (204) |
| GET | `/api/questoes` | opcional | pesquisa + filtros + paginação + destaque |
| GET | `/api/questoes/filtros` | pública | filtros suportados, disponibilidade nos dados e valores |
| GET | `/api/questoes/{id}` | opcional | detalhes de uma questão |
| GET | `/api/estatisticas` | pública | agregações do acervo |
| GET | `/api/painel/professor` | **professor** | painel analítico |
| GET | `/api/carrinho` | qualquer perfil | lista o carrinho da sessão |
| POST | `/api/carrinho/questoes` | qualquer perfil | adiciona `{"id": "..."}` (201; 200 se já estava) |
| DELETE | `/api/carrinho/questoes/{id}` | qualquer perfil | remove uma questão |
| DELETE | `/api/carrinho` | qualquer perfil | limpa o carrinho (204) |
| GET | `/api/carrinho/exportar?formato=pdf\|json` | qualquer perfil | exporta o simulado (gabarito só para professor) |
| GET | `/api/cache/metricas` | **professor** | hits, misses, hit rate |
| POST | `/api/cache/invalidar` | **professor** | invalida o cache de consultas |

"opcional": funciona sem token. Com token de professor, `gabarito` vem preenchido.

## Autenticação e perfis

```http
POST /api/auth/login
Content-Type: application/json

{"usuario": "prof.demo", "senha": "..."}
```

```json
{
  "access_token": "token_exemplo",
  "token_type": "bearer",
  "expira_em": 3600,
  "usuario": {"id": "prof.demo", "nome": "Professor Demo", "perfil": "professor",
              "permissoes": ["pesquisar", "filtrar", "carrinho", "ver_gabarito", "painel_analitico",
                             "exportar_simulado", "gerenciar_cache"]}
}
```

Nas demais requisições envie `Authorization: Bearer <access_token>`. A sessão (e o carrinho) expiram
após `SESSAO_TTL` segundos **sem uso**; cada requisição autenticada renova o prazo. Token expirado ou
inválido → `401 SESSAO_EXPIRADA` (o frontend deve voltar à tela de login).

| Perfil (`perfil`) | Grupo LDAP | Permissões |
|---|---|---|
| `estudante` | `cn=estudantes,ou=grupos,dc=enade,dc=local` | pesquisar, filtrar, carrinho, exportar sem gabarito |
| `professor` | `cn=professores,ou=grupos,dc=enade,dc=local` | tudo do estudante + ver gabarito, painel analítico, exportar com gabarito, gerenciar cache |

Estudante em recurso de professor → **403** `ACESSO_NEGADO`. Sem token em rota protegida → **401** `NAO_AUTENTICADO`.
Usuário do LDAP fora dos dois grupos → **403** `USUARIO_SEM_PERFIL` no login. Após `LOGIN_MAX_FALHAS`
senhas erradas → **429** `LOGIN_BLOQUEADO` por `LOGIN_JANELA_BLOQUEIO` segundos.

## Questão

```json
{
  "id": "sistemas-de-informacao-2023-fg-001",
  "ano": 2023,
  "area": "Computação",
  "curso": "Sistemas de Informação",
  "tipo_prova": "Formação Geral",
  "tipo_questao": "objetiva",
  "numero": 1,
  "texto_base": "Texto de apoio (ou null)",
  "enunciado": "Texto do enunciado da questão...",
  "alternativas": [{"letra": "A", "texto": "..."}, {"letra": "B", "texto": "..."}],
  "gabarito": "A",
  "anulada": false,
  "competencias": ["Raciocínio lógico"],
  "objetos_conhecimento": []
}
```

- `id` é único e estável (`curso-ano-tipo-numero`).
- `tipo_prova`: `"Formação Geral"` | `"Componente Específico"`. `tipo_questao`: `"objetiva"` | `"discursiva"`.
- `alternativas` é sempre lista (vazia em discursivas). `competencias`/`objetos_conhecimento` podem ser `[]`.
- `gabarito` é `null` quando: discursiva, anulada, não extraído, ou o usuário não é professor.
- `texto_base` e `objetos_conhecimento` são campos adicionais ao contrato inicial (o enunciado do ENADE
  costuma vir depois de um texto de apoio, que precisa ser exibido).

## `GET /api/questoes`

| Parâmetro | Tipo | Validação | Descrição | Situação |
|---|---|---|---|---|
| `q` | string | até 300 caracteres | texto (stemming PT-BR, sinônimos, sem acento) | implementado |
| `area` | string | exato | área | implementado |
| `curso` | string | exato | curso | implementado |
| `ano` | inteiro | 2004–2100 | ano da prova | implementado |
| `tipo_prova` | string | `Formação Geral`/`Componente Específico` (aceita `FG`/`CE`, sem acento) | tipo de prova | implementado |
| `tipo_questao` | string | `objetiva`/`discursiva` | tipo de questão | implementado |
| `competencia` | string | exato | competência | implementado; **depende dos dados** (a extração ainda não preenche `competencias`) |
| `pagina` | inteiro | ≥ 1 | página | implementado |
| `tamanho` | inteiro | 1–100; `pagina × tamanho ≤ 10000` | itens por página | implementado |

Todos os filtros são combináveis (AND). `GET /api/questoes/filtros` informa, em tempo real, quantas
questões possuem cada metadado (`documentos_com_dado`, `disponivel`) e os valores existentes (`valores`),
para montar os selects.

Resposta:

```json
{
  "total": 3, "pagina": 1, "tamanho": 10, "total_paginas": 1,
  "questoes": [{"...campos da Questão...": "", "destaques": {"enunciado": ["Analise os <mark>algoritmos</mark> de ordenação"]}}]
}
```

`destaques` traz trechos com os termos encontrados envoltos em `<mark>` por campo (`enunciado`,
`texto_base`, `alternativas`). O texto original vem escapado em HTML: é seguro renderizar o trecho
como HTML. Nenhum resultado → `200` com `questoes: []` (não é erro).
Header `X-Cache: HIT|MISS` indica se veio do cache.

## `GET /api/estatisticas`

```json
{
  "total_questoes": 1000,
  "por_area": [{"nome": "Computação", "quantidade": 300}],
  "por_ano": [{"nome": "2023", "quantidade": 200}],
  "por_tipo_questao": [{"nome": "objetiva", "quantidade": 700}, {"nome": "discursiva", "quantidade": 300}],
  "por_tipo_prova": [{"nome": "Formação Geral", "quantidade": 400}],
  "por_curso": [{"nome": "Sistemas de Informação", "quantidade": 120}],
  "competencias_por_ano": [{"competencia": "Raciocínio lógico", "total": 12,
                            "por_ano": [{"ano": 2021, "quantidade": 5}, {"ano": 2023, "quantidade": 7}]}]
}
```

Sem dados (ou índice ainda não criado) a estrutura é mantida com listas vazias e zero.
`por_ano` vem em ordem crescente de ano.

## Carrinho e exportação

O carrinho pertence à **sessão** (Redis), preserva a ordem de inclusão, não tem duplicatas e tem limite
`CARRINHO_MAX`. Respostas de adicionar/remover/listar:

```json
{"total": 2, "maximo": 100, "expira_em": 3600, "questoes": [ /* Questão */ ]}
```

`GET /api/carrinho/exportar?formato=json|pdf&incluir_gabarito=true|false` devolve arquivo para download
(`Content-Disposition: attachment`). O simulado inclui texto-base, enunciado, alternativas e metadados de
cada questão; o gabarito só entra para professor (padrão: com gabarito). Estudante pedindo
`incluir_gabarito=true` → 403. Carrinho vazio → 400 `CARRINHO_VAZIO`. Formato JSON: ver
`api/exemplos/simulado_exportado.json`.

## Erros

Todas as rotas usam o mesmo formato:

```json
{"erro": {"codigo": "QUESTAO_NAO_ENCONTRADA", "mensagem": "Questao 'x' nao encontrada."}}
```

Erros de validação (400) trazem também `detalhes: [{"campo": "tamanho", "mensagem": "..."}]`.

| HTTP | Códigos |
|---|---|
| 400 | `PARAMETROS_INVALIDOS`, `CONSULTA_INVALIDA`, `CARRINHO_VAZIO` |
| 401 | `NAO_AUTENTICADO`, `SESSAO_EXPIRADA`, `CREDENCIAIS_INVALIDAS` |
| 403 | `ACESSO_NEGADO`, `USUARIO_SEM_PERFIL` |
| 404 | `QUESTAO_NAO_ENCONTRADA`, `QUESTAO_NAO_ESTA_NO_CARRINHO`, `RECURSO_NAO_ENCONTRADO` |
| 409 | `CARRINHO_CHEIO` |
| 429 | `LOGIN_BLOQUEADO` |
| 500 | `ERRO_INTERNO` |
| 503 | `SERVICO_INDISPONIVEL` (Elasticsearch, Redis ou LDAP fora) |

## Cache

- Pesquisas, filtros e estatísticas ficam no Redis por `CACHE_TTL` segundos (chaves `enade:cache:v{versao}:...`).
- O cache guarda a resposta completa; o gabarito é retirado **depois**, conforme o perfil, então um
  estudante nunca recebe gabarito vindo do cache de um professor.
- Invalidação: `POST /api/cache/invalidar` incrementa a versão (O(1)); entradas antigas deixam de ser lidas
  e expiram sozinhas. Use após reindexar o acervo.
- Consistência: a entrada só é aceita se os parâmetros gravados forem idênticos aos pedidos; senão é descartada.
- Redis fora do ar: a pesquisa continua funcionando direto no Elasticsearch (`X-Cache: MISS`).
- Métricas: `GET /api/cache/metricas` (hits, misses, erros, hit rate total e por endpoint, chaves ativas).
