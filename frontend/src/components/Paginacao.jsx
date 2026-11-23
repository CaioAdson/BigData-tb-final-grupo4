
function Paginacao({ pagina, totalPaginas, aoMudarPagina }) {
  if (totalPaginas <= 1) return null

  return (
    <nav className="paginacao" aria-label="Paginação das questões">
      <button
        type="button"
        onClick={() => aoMudarPagina(pagina - 1)}
        disabled={pagina <= 1}
      >
        Anterior
      </button>

      <span>
        Página <strong>{pagina}</strong> de {totalPaginas}
      </span>

      <button
        type="button"
        onClick={() => aoMudarPagina(pagina + 1)}
        disabled={pagina >= totalPaginas}
      >
        Próxima
      </button>
    </nav>
  )
}

export default Paginacao
