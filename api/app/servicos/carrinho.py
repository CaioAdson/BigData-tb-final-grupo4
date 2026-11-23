"""Carrinho de questoes por sessao, guardado no Redis.

ZSET `enade:carrinho:{sid}`: membro = id da questao, score = momento da inclusao.
Assim a ordem de inclusao e preservada (vira a ordem do simulado) e nao ha duplicatas.
O TTL acompanha o da sessao (definido em add e renovado a cada requisicao autenticada).
"""
import time

from ..seguranca.sessoes import chave_carrinho


class CarrinhoCheio(Exception):
    pass


class Carrinho:
    def __init__(self, redis, ttl: int, maximo: int):
        self.redis = redis
        self.ttl = ttl
        self.maximo = maximo

    async def ids(self, sid: str) -> list[str]:
        return list(await self.redis.zrange(chave_carrinho(sid), 0, -1))

    async def adicionar(self, sid: str, questao_id: str) -> bool:
        """Retorna True se adicionou, False se ja estava no carrinho."""
        chave = chave_carrinho(sid)
        if await self.redis.zscore(chave, questao_id) is not None:
            await self.redis.expire(chave, self.ttl)
            return False
        if await self.redis.zcard(chave) >= self.maximo:
            raise CarrinhoCheio()
        pipe = self.redis.pipeline()
        pipe.zadd(chave, {questao_id: time.time()}, nx=True)
        pipe.expire(chave, self.ttl)
        adicionados, _ = await pipe.execute()
        return bool(adicionados)

    async def remover(self, sid: str, questao_id: str) -> bool:
        return bool(await self.redis.zrem(chave_carrinho(sid), questao_id))

    async def limpar(self, sid: str) -> None:
        await self.redis.delete(chave_carrinho(sid))

    async def expira_em(self, sid: str) -> int:
        ttl = await self.redis.ttl(chave_carrinho(sid))
        return int(ttl) if ttl and ttl > 0 else self.ttl
