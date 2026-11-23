
import api from './api'

export async function buscarQuestoes({
  pesquisa = '',
  area = '',
  ano = 2024,
  tipoProva = '',
  tipoQuestao = '',
  pagina = 1,
  tamanho = 10,
} = {}) {
  const parametros = {
    ano,
    pagina,
    tamanho,
  }

  if (pesquisa.trim()) parametros.q = pesquisa.trim()
  if (area) parametros.area = area
  if (tipoProva) parametros.tipo_prova = tipoProva
  if (tipoQuestao) parametros.tipo_questao = tipoQuestao

  const resposta = await api.get('/api/questoes', {
    params: parametros,
  })

  return resposta.data
}
