"""Autenticacao mutua API <-> Elasticsearch via Kerberos (SPNEGO/GSSAPI).

Fluxo (ativado com ES_AUTH=kerberos):
  1. A API obtem credenciais do seu principal (ex.: api/api@ENADE.LOCAL) a partir do
     keytab ES_KERBEROS_KEYTAB (nenhuma senha em variavel de ambiente).
  2. Cria um contexto GSSAPI para o servico ES_KERBEROS_SERVICO (HTTP@elasticsearch) com
     a flag MUTUAL_AUTHENTICATION e envia o ticket SPNEGO (`Authorization: Negotiate ...`)
     em POST /_security/api_key. O Elasticsearch valida o ticket com o keytab dele (realm kerb1).
  3. O Elasticsearch responde com `WWW-Authenticate: Negotiate <token>`. A API alimenta o
     contexto GSSAPI com ele: se o servidor nao for quem diz ser, `step()` falha e a API
     recusa a conexao. Isso e a autenticacao MUTUA (o cliente tambem autentica o servidor).
  4. A API key criada pertence ao proprio principal (mesmos papeis, ex.: somente leitura),
     expira em 1h e e renovada antes de expirar.
  Obs.: o grant `_kerberos` de /_security/oauth2/token nao serve aqui porque exige que a
  chamada ja venha autenticada por outro usuario com o privilegio manage_token.
"""
import base64
import logging
import time

log = logging.getLogger("enade.kerberos")


class FalhaAutenticacaoMutua(Exception):
    pass


def _gssapi():
    try:
        import gssapi  # type: ignore
    except ImportError as e:  # pragma: no cover - so ocorre sem a lib instalada
        raise RuntimeError("ES_AUTH=kerberos exige o pacote 'gssapi' (requirements-kerberos.txt)") from e
    return gssapi


def criar_contexto(servico: str, principal: str | None, keytab: str | None, gssapi=None):
    gssapi = gssapi or _gssapi()
    nome_servico = gssapi.Name(servico, gssapi.NameType.hostbased_service)
    credenciais = None
    if principal or keytab:
        store = {"client_keytab": keytab} if keytab else None
        nome = gssapi.Name(principal, gssapi.NameType.kerberos_principal) if principal else None
        credenciais = gssapi.Credentials(name=nome, usage="initiate", store=store)
    flags = [gssapi.RequirementFlag.mutual_authentication, gssapi.RequirementFlag.out_of_sequence_detection]
    return gssapi.SecurityContext(name=nome_servico, creds=credenciais, usage="initiate", flags=flags)


class ProvedorTokenKerberos:
    """Autentica no Elasticsearch via SPNEGO (verificando o servidor) e obtem uma API key."""

    def __init__(self, es_url: str, servico: str, principal: str | None, keytab: str | None,
                 http_post=None, fabrica_contexto=None, margem: int = 60):
        self.es_url = es_url.rstrip("/")
        self.servico = servico
        self.principal = principal
        self.keytab = keytab
        self._post = http_post
        self._fabrica = fabrica_contexto or (lambda: criar_contexto(servico, principal, keytab))
        self.margem = margem
        self.token: str | None = None
        self.expira_em = 0.0
        self.usuario_es: str | None = None

    async def _http_post(self, url: str, corpo: dict, headers: dict) -> tuple[int, dict, dict]:
        if self._post:
            return await self._post(url, corpo, headers)
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=corpo, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                return r.status, dict(r.headers), await r.json(content_type=None)

    def expirado(self) -> bool:
        return self.token is None or time.time() >= self.expira_em - self.margem

    async def obter_token(self) -> str:
        """Retorna a API key (valor `encoded`, usado no header `Authorization: ApiKey`)."""
        if not self.expirado():
            return self.token
        ctx = self._fabrica()
        ticket = ctx.step()
        status, headers, resposta = await self._http_post(
            f"{self.es_url}/_security/api_key",
            {"name": "enade-api-kerberos", "expiration": "1h"},
            {"Authorization": "Negotiate " + base64.b64encode(ticket).decode()},
        )
        if status != 200 or "encoded" not in (resposta or {}):
            raise FalhaAutenticacaoMutua(f"Elasticsearch recusou o ticket Kerberos (HTTP {status})")
        cabecalho = next((v for c, v in headers.items() if c.lower() == "www-authenticate"), "")
        partes = cabecalho.split()
        if len(partes) != 2 or partes[0].lower() != "negotiate":
            raise FalhaAutenticacaoMutua("Servidor nao devolveu token SPNEGO de resposta: autenticacao mutua impossivel")
        try:
            ctx.step(base64.b64decode(partes[1]))
        except Exception as e:
            raise FalhaAutenticacaoMutua("Token de resposta do servidor invalido (servidor nao autenticado)") from e
        if not getattr(ctx, "complete", True):
            raise FalhaAutenticacaoMutua("Contexto GSSAPI incompleto apos resposta do servidor")
        self.token = resposta["encoded"]
        expira_ms = resposta.get("expiration")
        self.expira_em = expira_ms / 1000 if expira_ms else time.time() + 3600
        self.usuario_es = self.principal
        log.info("Kerberos: autenticacao mutua com %s concluida (principal %s)", self.servico, self.principal)
        return self.token
