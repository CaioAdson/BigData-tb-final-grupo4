
import api from './api'

export async function buscarEstatisticas() {
  const resposta = await api.get('/api/estatisticas')
  return resposta.data
}
