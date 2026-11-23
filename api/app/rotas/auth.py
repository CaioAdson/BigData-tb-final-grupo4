"""Login via LDAP, sessao corrente e logout."""
import logging

from fastapi import APIRouter, Depends, Response
from starlette.concurrency import run_in_threadpool

from ..dependencias import Estado, UsuarioSessao, obter_estado, usuario_obrigatorio
from ..erros import ErroAPI, servico_indisponivel
from ..schemas import LoginEntrada, Token, Usuario, respostas_erro
from ..seguranca.ldap import CredenciaisInvalidas, LDAPIndisponivel, SemPerfil
from ..seguranca.sessoes import PERMISSOES

log = logging.getLogger("enade.auth")
router = APIRouter(prefix="/api/auth", tags=["Autenticação"])


def _usuario_publico(u: dict) -> dict:
    return {**u, "permissoes": PERMISSOES[u["perfil"]]}


@router.post(
    "/login",
    response_model=Token,
    summary="Login (LDAP)",
    description=(
        "Valida usuário e senha no servidor LDAP e identifica o perfil pelo grupo "
        "(`cn=professores` → `professor`, `cn=estudantes` → `estudante`).\n\n"
        "Retorna um token opaco de sessão. Envie-o nas demais requisições no header "
        "`Authorization: Bearer <access_token>`. A sessão fica no Redis e expira após `SESSAO_TTL` "
        "segundos sem uso (cada requisição renova o prazo).\n\n"
        f"Após `LOGIN_MAX_FALHAS` tentativas erradas o usuário fica bloqueado temporariamente (429)."),
    responses=respostas_erro(400, 401, 403, 429, 503),
)
async def login(entrada: LoginEntrada, estado: Estado = Depends(obter_estado)):
    cfg = estado.cfg
    try:
        if await estado.sessoes.bloqueado(entrada.usuario, cfg.login_max_falhas):
            raise ErroAPI(429, "LOGIN_BLOQUEADO",
                          "Muitas tentativas de login. Aguarde alguns minutos e tente novamente.")
    except ErroAPI:
        raise
    except Exception as e:
        raise servico_indisponivel("Redis (sessoes)") from e

    try:
        u = await run_in_threadpool(estado.autenticador.autenticar, entrada.usuario, entrada.senha)
    except CredenciaisInvalidas:
        await estado.sessoes.registrar_falha(entrada.usuario, cfg.login_janela_bloqueio)
        log.info("Login recusado para '%s'", entrada.usuario)
        raise ErroAPI(401, "CREDENCIAIS_INVALIDAS", "Usuario ou senha invalidos.")
    except SemPerfil:
        raise ErroAPI(403, "USUARIO_SEM_PERFIL",
                      "Usuario autenticado, mas nao pertence aos grupos de estudantes ou professores.")
    except LDAPIndisponivel as e:
        raise servico_indisponivel("LDAP") from e

    await estado.sessoes.limpar_falhas(entrada.usuario)
    usuario = {"id": u.id, "nome": u.nome, "perfil": u.perfil}
    token = await estado.sessoes.criar(usuario)
    log.info("Login de '%s' (%s)", u.id, u.perfil)
    return {"access_token": token, "token_type": "bearer", "expira_em": cfg.sessao_ttl,
            "usuario": _usuario_publico(usuario)}


@router.get("/me", response_model=Usuario, summary="Usuário da sessão",
            description="Dados e permissões do usuário autenticado. **Requer autenticação.**",
            responses=respostas_erro(401, 503))
async def eu(usuario: UsuarioSessao = Depends(usuario_obrigatorio)):
    return _usuario_publico(usuario.como_dict())


@router.post("/logout", status_code=204, summary="Encerrar sessão",
             description="Apaga a sessão e o carrinho do Redis. **Requer autenticação.**",
             responses=respostas_erro(401, 503))
async def logout(usuario: UsuarioSessao = Depends(usuario_obrigatorio), estado: Estado = Depends(obter_estado)):
    await estado.sessoes.encerrar(usuario.sid)
    return Response(status_code=204)
