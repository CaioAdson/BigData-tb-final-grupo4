"""Cache de consultas no Redis com TTL, invalidacao por versao e metricas de uso.

Chaves:
  enade:cache:versao                         -> inteiro; INCR invalida todo o cache em O(1)
  enade:cache:v{versao}:{endpoint}:{sha256}  -> JSON {"endpoint", "parametros", "dados"} com TTL
  enade:cache:metricas                       -> hash com hits/misses/erros (total e por endpoint)

Consistencia: a chave inclui a versao, entao apos invalidar nenhuma entrada antiga e lida
(elas expiram sozinhas pelo TTL). Na leitura, a entrada so e aceita se os parametros
gravados forem identicos aos pedidos (protege contra colisao/corrupcao); senao vira miss
e a chave e apagada.
"""
import hashlib
import json
import logging

log = logging.getLogger("enade.cache")

PREFIXO = "enade:cache"
CHAVE_VERSAO = f"{PREFIXO}:versao"
CHAVE_METRICAS = f"{PREFIXO}:metricas"


class CacheConsultas:
    def __init__(self, redis, ttl: int):
        self.redis = redis
        self.ttl = ttl

    @staticmethod
    def _hash(parametros: dict) -> str:
        conteudo = json.dumps(parametros, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(conteudo.encode()).hexdigest()

    async def versao(self) -> int:
        valor = await self.redis.get(CHAVE_VERSAO)
        return int(valor) if valor else 0

    async def chave(self, endpoint: str, parametros: dict) -> str:
        return f"{PREFIXO}:v{await self.versao()}:{endpoint}:{self._hash(parametros)}"

    async def _contar(self, endpoint: str, campo: str) -> None:
        try:
            pipe = self.redis.pipeline()
            pipe.hincrby(CHAVE_METRICAS, campo, 1)
            pipe.hincrby(CHAVE_METRICAS, f"{endpoint}:{campo}", 1)
            await pipe.execute()
        except Exception:  # metrica nunca derruba a requisicao
            pass

    async def obter(self, endpoint: str, parametros: dict):
        """Retorna os dados em cache ou None (miss). Falha do Redis = miss (degrada sem cache)."""
        try:
            chave = await self.chave(endpoint, parametros)
            bruto = await self.redis.get(chave)
        except Exception as e:
            log.warning("Redis indisponivel no cache (%s)", type(e).__name__)
            await self._contar(endpoint, "erros")
            return None
        if bruto is None:
            await self._contar(endpoint, "misses")
            return None
        try:
            entrada = json.loads(bruto)
            if entrada.get("endpoint") != endpoint or entrada.get("parametros") != json.loads(
                    json.dumps(parametros, ensure_ascii=False, default=str)):
                raise ValueError("entrada inconsistente")
            dados = entrada["dados"]
        except Exception:
            log.warning("Entrada de cache inconsistente descartada: %s", chave)
            try:
                await self.redis.delete(chave)
            except Exception:
                pass
            await self._contar(endpoint, "misses")
            return None
        await self._contar(endpoint, "hits")
        return dados

    async def salvar(self, endpoint: str, parametros: dict, dados) -> None:
        try:
            chave = await self.chave(endpoint, parametros)
            entrada = {"endpoint": endpoint, "parametros": parametros, "dados": dados}
            await self.redis.set(chave, json.dumps(entrada, ensure_ascii=False, default=str), ex=self.ttl)
        except Exception as e:
            log.warning("Falha ao gravar cache (%s)", type(e).__name__)

    async def invalidar(self) -> int:
        """Invalida todo o cache de consultas. Retorna a nova versao."""
        return int(await self.redis.incr(CHAVE_VERSAO))

    async def metricas(self) -> dict:
        bruto = await self.redis.hgetall(CHAVE_METRICAS)
        valores = {k: int(v) for k, v in bruto.items()}
        hits, misses, erros = valores.get("hits", 0), valores.get("misses", 0), valores.get("erros", 0)
        por_endpoint: dict[str, dict[str, int]] = {}
        for k, v in valores.items():
            if ":" in k:
                endpoint, campo = k.rsplit(":", 1)
                por_endpoint.setdefault(endpoint, {"hits": 0, "misses": 0, "erros": 0})[campo] = v
        versao = await self.versao()
        chaves = 0
        async for _ in self.redis.scan_iter(match=f"{PREFIXO}:v{versao}:*", count=500):
            chaves += 1
        total = hits + misses
        return {
            "hits": hits, "misses": misses, "erros": erros, "total_consultas": total,
            "hit_rate": round(hits / total, 4) if total else 0.0,
            "chaves_ativas": chaves, "ttl_segundos": self.ttl, "versao": versao,
            "por_endpoint": por_endpoint,
        }

    async def zerar_metricas(self) -> None:
        await self.redis.delete(CHAVE_METRICAS)
