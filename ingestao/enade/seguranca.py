"""Cliente Elasticsearch do pipeline com autenticacao mutua Kerberos (SPNEGO/GSSAPI).

Mesmo protocolo da API (api/app/seguranca/kerberos.py): ticket SPNEGO do principal do
consumidor -> POST /_security/api_key -> o token SPNEGO de resposta (WWW-Authenticate) e
validado no contexto GSSAPI (autenticacao mutua) -> API key do proprio principal.
"""
import base64
import json
import urllib.request

from elasticsearch import Elasticsearch

from . import config


def _token_kerberos() -> str:
    import gssapi
    servico = gssapi.Name(config.ES_KERBEROS_SERVICO, gssapi.NameType.hostbased_service)
    creds = None
    if config.ES_KERBEROS_PRINCIPAL or config.ES_KERBEROS_KEYTAB:
        nome = gssapi.Name(config.ES_KERBEROS_PRINCIPAL, gssapi.NameType.kerberos_principal) if config.ES_KERBEROS_PRINCIPAL else None
        creds = gssapi.Credentials(name=nome, usage="initiate",
                                   store={"client_keytab": config.ES_KERBEROS_KEYTAB} if config.ES_KERBEROS_KEYTAB else None)
    ctx = gssapi.SecurityContext(name=servico, creds=creds, usage="initiate",
                                 flags=[gssapi.RequirementFlag.mutual_authentication])
    ticket = ctx.step()
    corpo = json.dumps({"name": "enade-pipeline-kerberos", "expiration": "1h"}).encode()
    req = urllib.request.Request(f"{config.ES_URL.rstrip('/')}/_security/api_key", data=corpo, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Negotiate " + base64.b64encode(ticket).decode()})
    with urllib.request.urlopen(req, timeout=15) as r:
        resposta = json.load(r)
        cabecalho = r.headers.get("WWW-Authenticate", "")
    ctx.step(base64.b64decode(cabecalho.split()[1]))  # falha = servidor impostor
    if not ctx.complete:
        raise RuntimeError("autenticacao mutua Kerberos incompleta")
    return resposta["encoded"]


def criar_es(**kwargs) -> Elasticsearch:
    if config.ES_AUTH == "kerberos":
        return Elasticsearch(config.ES_URL, api_key=_token_kerberos(), **kwargs)
    return Elasticsearch(config.ES_URL, **kwargs)
