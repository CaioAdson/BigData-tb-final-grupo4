"""Configuracao da API via variaveis de ambiente (nenhum segredo no codigo).

Todas as variaveis estao documentadas no README (secao "Variaveis de ambiente da API").
"""
import os
from dataclasses import dataclass, field


def _lista(valor: str | None, padrao: list[str]) -> list[str]:
    if not valor:
        return padrao
    return [v.strip() for v in valor.split(",") if v.strip()]


@dataclass
class Config:
    # Elasticsearch
    es_url: str = "http://localhost:9200"
    es_index: str = "enade-questoes"
    es_timeout: int = 10
    es_auth: str = "nenhuma"  # nenhuma | kerberos
    es_kerberos_servico: str = "HTTP@elasticsearch"
    es_kerberos_principal: str | None = None
    es_kerberos_keytab: str | None = None

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str | None = None
    cache_ttl: int = 300
    sessao_ttl: int = 3600
    carrinho_max: int = 100

    # LDAP
    ldap_url: str = "ldap://localhost:389"
    ldap_bind_dn: str | None = None
    ldap_bind_password: str | None = None
    ldap_usuarios_dn: str = "ou=usuarios,dc=enade,dc=local"
    ldap_grupos_dn: str = "ou=grupos,dc=enade,dc=local"
    ldap_atributo_usuario: str = "uid"
    ldap_grupo_professor: str = "professores"
    ldap_grupo_estudante: str = "estudantes"
    ldap_timeout: int = 5
    login_max_falhas: int = 5
    login_janela_bloqueio: int = 300

    # HTTP
    cors_origens: list[str] = field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ])


def carregar() -> Config:
    e = os.getenv
    return Config(
        es_url=e("ES_URL", "http://localhost:9200"),
        es_index=e("ES_INDEX", "enade-questoes"),
        es_timeout=int(e("ES_TIMEOUT", "10")),
        es_auth=e("ES_AUTH", "nenhuma").lower(),
        es_kerberos_servico=e("ES_KERBEROS_SERVICO", "HTTP@elasticsearch"),
        es_kerberos_principal=e("ES_KERBEROS_PRINCIPAL") or None,
        es_kerberos_keytab=e("ES_KERBEROS_KEYTAB") or None,
        redis_url=e("REDIS_URL", "redis://localhost:6379/0"),
        redis_password=e("REDIS_PASSWORD") or None,
        cache_ttl=int(e("CACHE_TTL", "300")),
        sessao_ttl=int(e("SESSAO_TTL", "3600")),
        carrinho_max=int(e("CARRINHO_MAX", "100")),
        ldap_url=e("LDAP_URL", "ldap://localhost:389"),
        ldap_bind_dn=e("LDAP_BIND_DN") or None,
        ldap_bind_password=e("LDAP_BIND_PASSWORD") or None,
        ldap_usuarios_dn=e("LDAP_USUARIOS_DN", "ou=usuarios,dc=enade,dc=local"),
        ldap_grupos_dn=e("LDAP_GRUPOS_DN", "ou=grupos,dc=enade,dc=local"),
        ldap_atributo_usuario=e("LDAP_ATRIBUTO_USUARIO", "uid"),
        ldap_grupo_professor=e("LDAP_GRUPO_PROFESSOR", "professores"),
        ldap_grupo_estudante=e("LDAP_GRUPO_ESTUDANTE", "estudantes"),
        ldap_timeout=int(e("LDAP_TIMEOUT", "5")),
        login_max_falhas=int(e("LOGIN_MAX_FALHAS", "5")),
        login_janela_bloqueio=int(e("LOGIN_JANELA_BLOQUEIO", "300")),
        cors_origens=_lista(e("CORS_ORIGENS"), Config().cors_origens),
    )
