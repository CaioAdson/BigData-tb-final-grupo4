# ENADE Search — Frontend

Interface web do projeto ENADE Search, desenvolvida com React e Vite.

## Funcionalidades

- Pesquisa de questões do ENADE.
- Filtros por ano, tipo de prova e tipo de questão.
- Exibição das questões e alternativas.
- Exibição do gabarito e informações de qualidade da extração.
- Paginação dos resultados.
- Integração com a API por meio do Axios.

## Tecnologias

- React
- Vite
- JavaScript
- Axios
- React Router
- Recharts
- Lucide React

## Pré-requisitos

- Node.js
- npm
- API do ENADE Search em execução.

## Instalação

Na pasta `frontend`, execute:

```bash
npm install
```

## Configuração

Crie um arquivo `.env` com base no `.env.example`:

```env
VITE_API_URL=http://localhost:8001
```

## Executar em desenvolvimento

```bash
npm run dev
```

O Vite exibirá o endereço local da aplicação no terminal.

## Compilar para produção

```bash
npm run build
```

## Verificar código

```bash
npm run lint
```

## API

A aplicação consome os endpoints:

- `GET /api/health`
- `GET /api/questoes`
- `GET /api/estatisticas`

A API deve estar disponível no endereço configurado em `VITE_API_URL`.