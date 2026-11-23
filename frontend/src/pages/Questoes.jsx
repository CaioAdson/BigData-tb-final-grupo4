
import { useEffect, useState } from 'react'
import { buscarQuestoes } from '../services/servicoQuestoes'
import CartaoQuestao from '../components/CartaoQuestao'
import Paginacao from '../components/Paginacao'

function Questoes() {
  const [questoes, setQuestoes] = useState([])
  const [total, setTotal] = useState(0)
  const [pagina, setPagina] = useState(1)
  const [pesquisa, setPesquisa] = useState('')
  const [tipoProva, setTipoProva] = useState('')
  const [tipoQuestao, setTipoQuestao] = useState('')
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')

  const tamanho = 10
  const totalPaginas = Math.ceil(total / tamanho)

  useEffect(() => {
    let ativo = true

    async function carregarQuestoes() {
      try {
        setCarregando(true)
        setErro('')

        const dados = await buscarQuestoes({
          pesquisa,
          ano: 2024,
          tipoProva,
          tipoQuestao,
          pagina,
          tamanho,
        })

        if (ativo) {
          setQuestoes(dados.questoes || [])
          setTotal(dados.total || 0)
        }
      } catch (erroApi) {
        if (ativo) {
          setErro(
            erroApi.response?.data?.detail ||
            'Não foi possível carregar as questões. Verifique se a API está funcionando.'
          )
          setQuestoes([])
          setTotal(0)
        }
      } finally {
        if (ativo) setCarregando(false)
      }
    }

    carregarQuestoes()

    return () => {
      ativo = false
    }
  }, [pesquisa, tipoProva, tipoQuestao, pagina])

  function atualizarPesquisa(valor) {
    setPesquisa(valor)
    setPagina(1)
  }

  function atualizarTipoProva(valor) {
    setTipoProva(valor)
    setPagina(1)
  }

  function atualizarTipoQuestao(valor) {
    setTipoQuestao(valor)
    setPagina(1)
  }

  return (
    <main className="aplicacao">
      <header className="cabecalho">
        <div className="marca">
          <div className="marca-icone">E</div>
          <div>
            <strong>ENADE Search</strong>
            <span>Plataforma de consulta de questões</span>
          </div>
        </div>

        <span className="cabecalho-ano">Edição 2024</span>
      </header>

      <section className="conteudo">
        <div className="introducao">
          <span className="etiqueta">BANCO DE QUESTÕES OFICIAIS</span>
          <h1>Explore questões do ENADE</h1>
          <p>
            Pesquise e consulte questões da prova de Matemática de 2024.
          </p>
        </div>

        <section className="resumo">
          <div className="resumo-icone">▤</div>
          <div>
            <span>Questões encontradas</span>
            <strong>{carregando ? '...' : total}</strong>
          </div>
          <span className="resumo-descricao">Dados da API</span>
        </section>

        <section className="busca">
          <label htmlFor="pesquisa">Pesquisar questões</label>
          <input
            id="pesquisa"
            type="search"
            placeholder="Digite uma palavra ou trecho do enunciado..."
            value={pesquisa}
            onChange={(evento) => atualizarPesquisa(evento.target.value)}
          />
        </section>

        <section className="filtros">
          <div>
            <label htmlFor="tipo-prova">Tipo de prova</label>
            <select
              id="tipo-prova"
              value={tipoProva}
              onChange={(evento) => atualizarTipoProva(evento.target.value)}
            >
              <option value="">Todos</option>
              <option value="CE">Componente Específico (CE)</option>
              <option value="FG">Formação Geral (FG)</option>
            </select>
          </div>

          <div>
            <label htmlFor="tipo-questao">Tipo de questão</label>
            <select
              id="tipo-questao"
              value={tipoQuestao}
              onChange={(evento) => atualizarTipoQuestao(evento.target.value)}
            >
              <option value="">Todos</option>
              <option value="objetiva">Objetiva</option>
              <option value="discursiva">Discursiva</option>
            </select>
          </div>

          <div>
            <label htmlFor="ano">Ano</label>
            <select id="ano" value="2024" disabled>
              <option value="2024">2024</option>
            </select>
          </div>
        </section>

        <div className="lista-cabecalho">
          <div>
            <h2>Questões disponíveis</h2>
            <p>Questões oficiais extraídas da prova de 2024.</p>
          </div>
          <span>{total} resultado(s)</span>
        </div>

        {carregando && (
          <div className="mensagem estado-carregando">
            Carregando questões...
          </div>
        )}

        {!carregando && erro && (
          <div className="mensagem estado-erro">
            <strong>Não foi possível carregar os dados.</strong>
            <p>{erro}</p>
            <button type="button" onClick={() => setPagina(pagina)}>
              Tentar novamente
            </button>
          </div>
        )}

        {!carregando && !erro && questoes.length === 0 && (
          <div className="mensagem">
            Nenhuma questão encontrada com os filtros informados.
          </div>
        )}

        {!carregando && !erro && questoes.length > 0 && (
          <div className="lista-questoes">
            {questoes.map((questao, indice) => (
              <CartaoQuestao
                key={questao.id || `${questao.numero}-${indice}`}
                questao={questao}
              />
            ))}
          </div>
        )}

        {!carregando && !erro && (
          <Paginacao
            pagina={pagina}
            totalPaginas={totalPaginas}
            aoMudarPagina={setPagina}
          />
        )}
      </section>

      <footer className="rodape">
        ENADE Search · Projeto de Big Data · Dados oficiais do ENADE 2024
      </footer>
    </main>
  )
}

export default Questoes
