"""Sessoes no Redis, perfis e permissoes.

O token entregue no login e opaco (aleatorio, 256 bits). No Redis guardamos apenas o
SHA-256 dele, entao um dump do Redis nao permite sequestrar sessoes.

  enade:sessao:{sid}   -> JSON do usuario, TTL = SESSAO_TTL (renovado a cada uso: expiracao deslizante)
  enade:carrinho:{sid} -> ZSET com ids de questoes, mesmo TTL da sessao
  enade:login:falhas:{usuario} -> contador de falhas de login (bloqueio temporario)
"""
import hashlib
import json
import secrets

PERMISSOES = {
    "estudante": ["pesquisar", "filtrar", "carrinho", "exportar_sem_gabarito"],
    "professor": ["pesquisar", "filtrar", "carrinho", "ver_gabarito", "painel_analitico",
                  "exportar_simulado", "gerenciar_cache"],
}


def tem_permissao(perfil: str | None, permissao: str) -> bool:
    return permissao in PERMISSOES.get(perfil or "", [])


def id_sessao(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def chave_sessao(sid: str) -> str:
    return f"enade:sessao:{sid}"


def chave_carrinho(sid: str) -> str:
    return f"enade:carrinho:{sid}"


class GerenciadorSessoes:
    def __init__(self, redis, ttl: int):
        self.redis = redis
        self.ttl = ttl

    async def criar(self, usuario: dict) -> str:
        token = secrets.token_urlsafe(32)
        await self.redis.set(chave_sessao(id_sessao(token)), json.dumps(usuario, ensure_ascii=False), ex=self.ttl)
        return token

    async def obter(self, token: str) -> tuple[str, dict] | None:
        """Retorna (sid, usuario) e renova o TTL da sessao e do carrinho; None se expirada."""
        sid = id_sessao(token)
        bruto = await self.redis.get(chave_sessao(sid))
        if not bruto:
            return None
        pipe = self.redis.pipeline()
        pipe.expire(chave_sessao(sid), self.ttl)
        pipe.expire(chave_carrinho(sid), self.ttl)
        await pipe.execute()
        return sid, json.loads(bruto)

    async def encerrar(self, sid: str) -> None:
        await self.redis.delete(chave_sessao(sid), chave_carrinho(sid))

    async def ttl_restante(self, sid: str) -> int:
        ttl = await self.redis.ttl(chave_sessao(sid))
        return max(int(ttl), 0)

    # ---- protecao contra forca bruta no login
    async def bloqueado(self, login: str, maximo: int) -> bool:
        valor = await self.redis.get(f"enade:login:falhas:{login.lower()}")
        return bool(valor) and int(valor) >= maximo

    async def registrar_falha(self, login: str, janela: int) -> None:
        chave = f"enade:login:falhas:{login.lower()}"
        pipe = self.redis.pipeline()
        pipe.incr(chave)
        pipe.expire(chave, janela)
        await pipe.execute()

    async def limpar_falhas(self, login: str) -> None:
        await self.redis.delete(f"enade:login:falhas:{login.lower()}")
