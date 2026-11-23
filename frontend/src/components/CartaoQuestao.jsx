
function CartaoQuestao({ questao }) {
  const enunciado =
    questao.enunciado ||
    questao.texto_base ||
    questao.texto_bruto ||
    'Enunciado não disponível.'

  const alternativas = Array.isArray(questao.alternativas)
    ? questao.alternativas
    : []

  return (
    <article className="questao-card">
      <div className="questao-topo">
        <div>
          <span className="questao-identificacao">
            QUESTÃO {questao.numero ?? '—'}
          </span>
          <h2>{questao.area || 'Área não informada'}</h2>
        </div>

        <span className="questao-ano">{questao.ano || 2024}</span>
      </div>

      <div className="questao-informacoes">
        <span>{questao.tipo_prova || 'Prova não informada'}</span>
        <span>{questao.tipo_questao || 'Tipo não informado'}</span>
        {questao.anulada && <span className="questao-anulada">Anulada</span>}
      </div>

      <p className="questao-enunciado">{enunciado}</p>

      {alternativas.length > 0 && (
        <div className="alternativas">
          {alternativas.map((alternativa, indice) => {
            const letra = alternativa.letra || String.fromCharCode(65 + indice)

            return (
              <div className="alternativa" key={`${letra}-${indice}`}>
                <strong>{letra}</strong>
                <span>{alternativa.texto || 'Texto não disponível.'}</span>
              </div>
            )
          })}
        </div>
      )}

      {questao.gabarito && (
        <div className="questao-gabarito">
          <strong>Gabarito:</strong> {questao.gabarito}
        </div>
      )}

      {questao.midia_pendente && (
        <p className="questao-aviso">
          Esta questão possui mídia que ainda precisa ser conferida.
        </p>
      )}

      {questao.qualidade?.segmentacao_incerta && (
        <p className="questao-aviso">
          Atenção: a segmentação do texto desta questão é incerta.
        </p>
      )}

      {questao.qualidade?.alternativas_incompletas && (
        <p className="questao-aviso">
          Atenção: podem existir alternativas incompletas.
        </p>
      )}
    </article>
  )
}

export default CartaoQuestao
