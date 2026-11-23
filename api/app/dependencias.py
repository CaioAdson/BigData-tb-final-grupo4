"""Dependencias compartilhadas: conexoes, usuario autenticado e controle de acesso por perfil."""
import logging
from dataclasses import dataclass

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Config
from .erros import ErroAPI, nao_autenticado, sem_permissao, servico_indisponivel
from .seguranca.sessoes import GerenciadorSessoes, tem_permissao
from .servicos.cache import CacheConsultas
from .servicos.carrinho import Carrinho

log = logging.getLogger("enade.api")

esquema_bearer = HTTPBearer(
    auto_error=False,
    description="Token obtido em POST /api/auth/login. Envie `Authorization: Bearer <access_token>`.",
)


@dataclass
class Estado:
    cfg: Config
    es: AsyncElasticsearch
    redis: object
    cache: CacheConsultas
    sessoes: GerenciadorSessoes
    carrinho: Carrinho
    autenticador: object  # AutenticadorLDAP
    kerberos: object | None = None  # ProvedorTokenKerberos


@dataclass
class UsuarioSessao:
    sid: str
    id: str
    nome: str
    perfil: str

    def pode(self, permissao: str) -> bool:
        return tem_permissao(self.perfil, permissao)

    def como_dict(self) -> dict:
        return {"id": self.id, "nome": self.nome, "perfil": self.perfil}


def obter_estado(request: Request) -> Estado:
    return request.app.state.enade


async def obter_es(estado: Estado = Depends(obter_estado)) -> AsyncElasticsearch:
    """Com ES_AUTH=kerberos, renova o token (autenticacao mutua) antes de expirar."""
    if estado.kerberos is not None and estado.kerberos.expirado():
        try:
            token = await estado.kerberos.obter_token()
        except Exception as e:
            log.error("Falha Kerberos com o Elasticsearch: %s", e)
            raise servico_indisponivel("Elasticsearch (Kerberos)") from e
        antigo = estado.es
        estado.es = AsyncElasticsearch(estado.cfg.es_url, api_key=token, request_timeout=estado.cfg.es_timeout)
        await antigo.close()
    return estado.es


async def usuario_opcional(
    credenciais: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
    estado: Estado = Depends(obter_estado),
) -> UsuarioSessao | None:
    """Rotas publicas: anonimo e permitido, mas um token enviado precisa ser valido."""
    if credenciais is None:
        return None
    try:
        sessao = await estado.sessoes.obter(credenciais.credentials)
    except Exception as e:
        raise servico_indisponivel("Redis (sessoes)") from e
    if sessao is None:
        raise ErroAPI(401, "SESSAO_EXPIRADA", "Sessao expirada ou token invalido. Faca login novamente.",
                      headers={"WWW-Authenticate": "Bearer"})
    sid, u = sessao
    return UsuarioSessao(sid=sid, id=u["id"], nome=u["nome"], perfil=u["perfil"])


async def usuario_obrigatorio(usuario: UsuarioSessao | None = Depends(usuario_opcional)) -> UsuarioSessao:
    if usuario is None:
        raise nao_autenticado()
    return usuario


def exigir_permissao(permissao: str, mensagem: str | None = None):
    async def _verificar(usuario: UsuarioSessao = Depends(usuario_obrigatorio)) -> UsuarioSessao:
        if not usuario.pode(permissao):
            raise sem_permissao(mensagem or "Recurso exclusivo para professores.")
        return usuario
    return _verificar

