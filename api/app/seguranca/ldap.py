"""Autenticacao de usuarios no LDAP e identificacao do perfil.

Fluxo (padrao "search then bind"):
  1. Conexao de servico (LDAP_BIND_DN/LDAP_BIND_PASSWORD, ou anonima) procura o usuario
     por `uid` dentro de LDAP_USUARIOS_DN. O valor digitado e escapado (anti LDAP injection).
  2. Bind com o DN encontrado + senha informada: e o LDAP que valida a senha; a API
     nunca le nem guarda senhas.
  3. O perfil vem da participacao em grupos (groupOfNames) em LDAP_GRUPOS_DN:
     cn=professores -> "professor"; cn=estudantes -> "estudante". Professor tem precedencia.
"""
import logging
from dataclasses import dataclass

from ldap3 import NONE, SIMPLE, Connection, Server
from ldap3.core.exceptions import (LDAPBindError, LDAPException, LDAPInvalidCredentialsResult,
                                   LDAPSocketOpenError)
from ldap3.utils.conv import escape_filter_chars

from ..config import Config

log = logging.getLogger("enade.ldap")


class CredenciaisInvalidas(Exception):
    pass


class SemPerfil(Exception):
    pass


class LDAPIndisponivel(Exception):
    pass


@dataclass
class UsuarioLDAP:
    id: str
    nome: str
    perfil: str
    dn: str


class AutenticadorLDAP:
    def __init__(self, cfg: Config, servidor: Server | None = None, estrategia=None):
        self.cfg = cfg
        # `servidor`/`estrategia` permitem injetar o servidor MOCK do ldap3 nos testes.
        self.servidor = servidor or Server(cfg.ldap_url, get_info=NONE, connect_timeout=cfg.ldap_timeout)
        self.estrategia = estrategia

    def _conectar(self, usuario=None, senha=None) -> Connection:
        kwargs = {"user": usuario, "password": senha, "receive_timeout": self.cfg.ldap_timeout,
                  "raise_exceptions": True}
        if usuario:
            kwargs["authentication"] = SIMPLE
        if self.estrategia:
            kwargs["client_strategy"] = self.estrategia
        conn = Connection(self.servidor, **kwargs)
        conn.bind()
        return conn

    def autenticar(self, login: str, senha: str) -> UsuarioLDAP:
        login = (login or "").strip()
        # Senha vazia faria um "unauthenticated bind" que o LDAP aceita: bloquear sempre.
        if not login or not senha:
            raise CredenciaisInvalidas()
        try:
            servico = self._conectar(self.cfg.ldap_bind_dn, self.cfg.ldap_bind_password)
        except LDAPSocketOpenError as e:
            raise LDAPIndisponivel() from e
        except LDAPException as e:
            log.error("Bind de servico no LDAP falhou: %s", type(e).__name__)
            raise LDAPIndisponivel() from e
        try:
            filtro = f"(&(objectClass=inetOrgPerson)({self.cfg.ldap_atributo_usuario}={escape_filter_chars(login)}))"
            servico.search(self.cfg.ldap_usuarios_dn, filtro, attributes=["cn", "displayName", self.cfg.ldap_atributo_usuario])
            if len(servico.entries) != 1:
                raise CredenciaisInvalidas()
            entrada = servico.entries[0]
            dn = entrada.entry_dn
            attrs = entrada.entry_attributes_as_dict
            nome = str((attrs.get("displayName") or attrs.get("cn") or [login])[0])

            try:
                self._conectar(dn, senha).unbind()
            except (LDAPBindError, LDAPInvalidCredentialsResult) as e:
                raise CredenciaisInvalidas() from e

            servico.search(self.cfg.ldap_grupos_dn,
                           f"(&(objectClass=groupOfNames)(member={escape_filter_chars(dn)}))",
                           attributes=["cn"])
            grupos = {str(g.cn.value).lower() for g in servico.entries}
        except LDAPSocketOpenError as e:
            raise LDAPIndisponivel() from e
        finally:
            try:
                servico.unbind()
            except Exception:
                pass

        if self.cfg.ldap_grupo_professor.lower() in grupos:
            perfil = "professor"
        elif self.cfg.ldap_grupo_estudante.lower() in grupos:
            perfil = "estudante"
        else:
            raise SemPerfil()
        return UsuarioLDAP(id=login, nome=nome, perfil=perfil, dn=dn)


__all__ = ["AutenticadorLDAP", "UsuarioLDAP", "CredenciaisInvalidas", "SemPerfil", "LDAPIndisponivel"]
