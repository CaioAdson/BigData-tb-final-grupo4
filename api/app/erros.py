"""Formato unico de erro da API.

Toda resposta de erro segue:
    {"erro": {"codigo": "CODIGO_EM_MAIUSCULAS", "mensagem": "Texto legivel.", "detalhes": [...]}}
`detalhes` so aparece em erros de validacao de parametros.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("enade.api")


class ErroAPI(Exception):
    def __init__(self, status: int, codigo: str, mensagem: str, detalhes: list | None = None,
                 headers: dict | None = None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhes = detalhes
        self.headers = headers


def corpo_erro(codigo: str, mensagem: str, detalhes: list | None = None) -> dict:
    erro = {"codigo": codigo, "mensagem": mensagem}
    if detalhes:
        erro["detalhes"] = detalhes
    return {"erro": erro}


# Atalhos usados pelas rotas
def nao_autenticado(mensagem="Autenticacao necessaria. Envie o header 'Authorization: Bearer <token>'."):
    return ErroAPI(401, "NAO_AUTENTICADO", mensagem, headers={"WWW-Authenticate": "Bearer"})


def sem_permissao(mensagem="Seu perfil nao tem permissao para acessar este recurso."):
    return ErroAPI(403, "ACESSO_NEGADO", mensagem)


def servico_indisponivel(servico: str):
    return ErroAPI(503, "SERVICO_INDISPONIVEL", f"Servico {servico} indisponivel no momento. Tente novamente.")


CODIGOS_HTTP = {
    400: "PARAMETROS_INVALIDOS",
    401: "NAO_AUTENTICADO",
    403: "ACESSO_NEGADO",
    404: "RECURSO_NAO_ENCONTRADO",
    405: "METODO_NAO_PERMITIDO",
    409: "CONFLITO",
    429: "MUITAS_REQUISICOES",
    500: "ERRO_INTERNO",
    503: "SERVICO_INDISPONIVEL",
}


def _detalhe_validacao(e: dict) -> dict:
    loc = [str(p) for p in e.get("loc", []) if p not in ("query", "body", "path")]
    return {"campo": ".".join(loc) or None, "mensagem": e.get("msg", "valor invalido")}


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErroAPI)
    async def _erro_api(_: Request, exc: ErroAPI):
        return JSONResponse(corpo_erro(exc.codigo, exc.mensagem, exc.detalhes),
                            status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validacao(_: Request, exc: RequestValidationError):
        detalhes = [_detalhe_validacao(e) for e in exc.errors()]
        return JSONResponse(
            corpo_erro("PARAMETROS_INVALIDOS", "Um ou mais parametros sao invalidos.", detalhes),
            status_code=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        codigo = CODIGOS_HTTP.get(exc.status_code, "ERRO_HTTP")
        mensagem = exc.detail if isinstance(exc.detail, str) else codigo
        if exc.status_code == 404 and mensagem == "Not Found":
            mensagem = "Rota nao encontrada."
        if exc.status_code == 405:
            mensagem = "Metodo HTTP nao permitido nesta rota."
        return JSONResponse(corpo_erro(codigo, mensagem), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _inesperado(_: Request, exc: Exception):
        log.exception("Erro nao tratado: %s", exc)
        return JSONResponse(corpo_erro("ERRO_INTERNO", "Erro interno do servidor."), status_code=500)
