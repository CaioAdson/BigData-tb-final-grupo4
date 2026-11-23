"""Contrato de dados da API (o que o frontend envia e recebe).

Os modelos aqui sao a fonte da verdade do Swagger (/docs) e dos exemplos em api/exemplos/.
O frontend NAO precisa conhecer a estrutura interna do Elasticsearch nem do Redis.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Perfil = Literal["estudante", "professor"]
TipoQuestao = Literal["objetiva", "discursiva"]
TipoProva = Literal["Formação Geral", "Componente Específico"]


# ------------------------------------------------------------------ erros
class ErroDetalhe(BaseModel):
    campo: str | None = None
    mensagem: str


class ErroCorpo(BaseModel):
    codigo: str = Field(examples=["QUESTAO_NAO_ENCONTRADA"])
    mensagem: str = Field(examples=["Nenhuma questão encontrada para os filtros informados."])
    detalhes: list[ErroDetalhe] | None = Field(default=None, description="Somente em erros de validação (400).")


class Erro(BaseModel):
    erro: ErroCorpo


def respostas_erro(*status: int) -> dict:
    """Bloco `responses=` do FastAPI com o formato padrao de erro."""
    descricoes = {
        400: "Parâmetros inválidos (codigo PARAMETROS_INVALIDOS).",
        401: "Usuário não autenticado ou token expirado (NAO_AUTENTICADO / SESSAO_EXPIRADA).",
        403: "Usuário sem permissão para o recurso (ACESSO_NEGADO).",
        404: "Recurso não encontrado.",
        409: "Conflito com o estado atual.",
        429: "Muitas tentativas (LOGIN_BLOQUEADO).",
        503: "Elasticsearch, Redis ou LDAP indisponível (SERVICO_INDISPONIVEL).",
    }
    return {s: {"model": Erro, "description": descricoes[s]} for s in status}


# ------------------------------------------------------------------ questoes
class Alternativa(BaseModel):
    letra: str = Field(examples=["A"])
    texto: str = Field(examples=["Texto da alternativa A"])


class Questao(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "id": "sistemas-de-informacao-2023-fg-001", "ano": 2023, "area": "Computação",
        "curso": "Sistemas de Informação", "tipo_prova": "Formação Geral", "tipo_questao": "objetiva",
        "numero": 1, "texto_base": "Texto de apoio...", "enunciado": "Texto do enunciado da questão...",
        "alternativas": [{"letra": "A", "texto": "Texto da alternativa A"},
                         {"letra": "B", "texto": "Texto da alternativa B"}],
        "gabarito": "A", "anulada": False, "competencias": ["Raciocínio lógico"],
        "objetos_conhecimento": [],
    }})

    id: str = Field(description="Identificador único e estável da questão.")
    ano: int
    area: str
    curso: str
    tipo_prova: TipoProva
    tipo_questao: TipoQuestao
    numero: int
    texto_base: str | None = Field(default=None, description="Texto de apoio que antecede o enunciado, se houver.")
    enunciado: str
    alternativas: list[Alternativa] = Field(default_factory=list, description="Vazia em questões discursivas.")
    gabarito: str | None = Field(
        default=None,
        description="Letra correta. null quando não se aplica (discursiva/anulada), não está disponível "
                    "ou o perfil do usuário não tem acesso a gabaritos (somente professor).")
    anulada: bool = False
    competencias: list[str] = Field(default_factory=list)
    objetos_conhecimento: list[str] = Field(default_factory=list)


class QuestaoPesquisa(Questao):
    destaques: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Trechos com os termos pesquisados envoltos em <mark>...</mark>, por campo "
                    "(enunciado, texto_base, alternativas). Vazio quando não há `q`.",
        examples=[{"enunciado": ["Sobre <mark>algoritmos</mark> de ordenação..."]}])


class RespostaQuestoes(BaseModel):
    total: int = Field(examples=[100])
    pagina: int = Field(examples=[1])
    tamanho: int = Field(examples=[10])
    total_paginas: int = Field(examples=[10])
    questoes: list[QuestaoPesquisa]


class FiltroDisponivel(BaseModel):
    parametro: str
    tipo: str
    descricao: str
    implementado: bool = True
    depende_de_dados: bool = Field(description="True quando o filtro só tem efeito se o índice tiver o metadado.")
    documentos_com_dado: int = Field(description="Quantas questões no índice possuem esse metadado.")
    disponivel: bool = Field(description="True quando há dados no índice para este filtro.")
    valores: list[str] = Field(default_factory=list, description="Valores existentes (para montar selects).")


class RespostaFiltros(BaseModel):
    total_questoes: int
    filtros: list[FiltroDisponivel]


# ------------------------------------------------------------------ estatisticas
class ItemContagem(BaseModel):
    nome: str
    quantidade: int


class ContagemAno(BaseModel):
    ano: int
    quantidade: int


class CompetenciaAno(BaseModel):
    competencia: str
    total: int
    por_ano: list[ContagemAno]


class Estatisticas(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "total_questoes": 1000,
        "por_area": [{"nome": "Computação", "quantidade": 300}],
        "por_ano": [{"nome": "2023", "quantidade": 200}],
        "por_tipo_questao": [{"nome": "objetiva", "quantidade": 700}, {"nome": "discursiva", "quantidade": 300}],
        "por_tipo_prova": [{"nome": "Formação Geral", "quantidade": 400}],
        "por_curso": [{"nome": "Sistemas de Informação", "quantidade": 120}],
        "competencias_por_ano": [{"competencia": "Raciocínio lógico", "total": 12,
                                  "por_ano": [{"ano": 2021, "quantidade": 5}, {"ano": 2023, "quantidade": 7}]}],
    }})

    total_questoes: int = 0
    por_area: list[ItemContagem] = Field(default_factory=list)
    por_ano: list[ItemContagem] = Field(default_factory=list)
    por_tipo_questao: list[ItemContagem] = Field(default_factory=list)
    por_tipo_prova: list[ItemContagem] = Field(default_factory=list)
    por_curso: list[ItemContagem] = Field(default_factory=list)
    competencias_por_ano: list[CompetenciaAno] = Field(
        default_factory=list, description="Histograma de questões por competência ao longo dos anos.")


class QualidadeIndice(BaseModel):
    anuladas: int
    sem_gabarito: int
    segmentacao_incerta: int
    alternativas_incompletas: int
    midia_pendente: int
    sem_competencias: int


class MetricasCache(BaseModel):
    hits: int
    misses: int
    erros: int
    total_consultas: int
    hit_rate: float = Field(description="hits / (hits + misses), entre 0 e 1.")
    chaves_ativas: int
    ttl_segundos: int
    versao: int = Field(description="Versão atual do cache; muda a cada invalidação.")
    por_endpoint: dict[str, dict[str, int]] = Field(default_factory=dict)


class PainelProfessor(BaseModel):
    estatisticas: Estatisticas
    gabaritos_por_ano: list[ContagemAno] = Field(description="Questões objetivas com gabarito disponível, por ano.")
    anuladas_por_ano: list[ContagemAno]
    qualidade: QualidadeIndice
    cache: MetricasCache


# ------------------------------------------------------------------ auth
class LoginEntrada(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"usuario": "prof.demo", "senha": "sua-senha"}})
    usuario: str = Field(min_length=1, max_length=128, description="Login (uid) no LDAP.")
    senha: str = Field(min_length=1, max_length=256)


class Usuario(BaseModel):
    id: str = Field(examples=["prof.demo"])
    nome: str = Field(examples=["Professor Demo"])
    perfil: Perfil
    permissoes: list[str] = Field(examples=[["pesquisar", "filtrar", "ver_gabarito", "painel_analitico",
                                             "exportar_simulado", "gerenciar_cache"]])


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expira_em: int = Field(description="Segundos até a sessão expirar sem uso (renovada a cada requisição).")
    usuario: Usuario


# ------------------------------------------------------------------ carrinho
class ItemCarrinhoEntrada(BaseModel):
    id: str = Field(min_length=1, max_length=200, examples=["sistemas-de-informacao-2023-fg-001"])


class Carrinho(BaseModel):
    total: int
    maximo: int
    expira_em: int = Field(description="Segundos até o carrinho expirar (acompanha a sessão).")
    questoes: list[Questao]


class InvalidacaoCache(BaseModel):
    versao: int
    mensagem: str
