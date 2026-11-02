import json
import tempfile
import unittest
from pathlib import Path

from enade.extrator import extrair_prova, parse_bloco, ler_gabarito
from enade.modelos import gerar_id, validar_documento
from tests.fabrica_pdf import gerar_demo


class TestParseBloco(unittest.TestCase):
    def test_alternativas_ignoram_linhas_que_comecam_com_A(self):
        linhas = ["A vida em sociedade exige regras.", "Com base no texto, assinale a correta.",
                  "A respeito do tema.", "A  um", "B  dois", "C  tres", "D  quatro", "E  cinco"]
        r = parse_bloco(linhas, discursiva=False)
        self.assertEqual([a["letra"] for a in r["alternativas"]], list("ABCDE"))
        self.assertEqual(r["alternativas"][0]["texto"], "um")
        self.assertTrue(r["texto_base"].startswith("A vida"))
        self.assertTrue(r["enunciado"].startswith("Com base"))

    def test_alternativa_com_continuacao_em_varias_linhas(self):
        linhas = ["Assinale a correta.", "A  primeira parte", "da alternativa a", "B  b", "C  c", "D  d", "E  e"]
        r = parse_bloco(linhas, False)
        self.assertEqual(r["alternativas"][0]["texto"], "primeira parte da alternativa a")

    def test_sem_comando_marca_incerteza(self):
        r = parse_bloco(["texto qualquer sem comando", "A  a", "B  b", "C  c", "D  d", "E  e"], False)
        self.assertTrue(r["segmentacao_incerta"])


class TestModelos(unittest.TestCase):
    def test_id_deterministico(self):
        self.assertEqual(gerar_id("Sistemas de Informação", 2021, "CE", 9), "sistemas-de-informacao-2021-ce-009")
        self.assertEqual(gerar_id("Sistemas de Informação", 2021, "CE", 9), gerar_id("Sistemas de Informação", 2021, "CE", 9))

    def test_validacao(self):
        self.assertTrue(validar_documento("x"))
        self.assertTrue(validar_documento({"id": "x", "curso": "T"}))


class TestExtracaoPDF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        gerar_demo(base)
        cls.docs = extrair_prova(base / "demo_prova.pdf", base / "demo_gabarito.pdf",
                                 area="Computação", curso="Sistemas de Informação Demo", ano=2021, qtd_fg=3)
        cls.por_num = {d["numero"]: d for d in cls.docs}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_quantidade_e_ignora_questionario(self):
        self.assertEqual(sorted(self.por_num), [1, 2, 3, 4])

    def test_todos_validos(self):
        for d in self.docs:
            self.assertEqual(validar_documento(d), [], d["id"])
            json.dumps(d, ensure_ascii=False)  # serializavel

    def test_q1_objetiva_com_gabarito(self):
        d = self.por_num[1]
        self.assertEqual(d["tipo_questao"], "objetiva")
        self.assertEqual(d["tipo_prova"], "FG")
        self.assertEqual(d["gabarito"], "C")
        self.assertEqual(len(d["alternativas"]), 5)
        self.assertTrue(d["texto_base"].startswith("A ética profissional"))
        self.assertTrue(d["enunciado"].startswith("Com base"))
        self.assertNotIn("R012021A", d["texto_bruto"])  # ruido removido
        self.assertFalse(any(d["qualidade"].values()))

    def test_q2_imagem_pendente(self):
        d = self.por_num[2]
        self.assertTrue(d["midia_pendente"])
        self.assertEqual([m["tipo"] for m in d["midia"] if m["tipo"] == "imagem"], ["imagem"])
        self.assertEqual(d["gabarito"], "B")

    def test_q3_discursiva_com_tabela_markdown(self):
        d = self.por_num[3]
        self.assertEqual(d["tipo_questao"], "discursiva")
        self.assertEqual(d["alternativas"], [])
        self.assertIsNone(d["gabarito"])
        tabelas = [m for m in d["midia"] if m["tipo"] == "tabela"]
        self.assertEqual(len(tabelas), 1)
        self.assertIn("| Sistema | p95 (ms) | Docs/s |", tabelas[0]["conteudo"])
        self.assertEqual(d["origem"]["pagina_inicio"], 2)

    def test_q4_anulada_nao_descartada_e_ce(self):
        d = self.por_num[4]
        self.assertTrue(d["anulada"])
        self.assertIsNone(d["gabarito"])
        self.assertEqual(d["tipo_prova"], "CE")

    def test_rastreabilidade(self):
        for d in self.docs:
            self.assertEqual(d["origem"]["pdf"], "demo_prova.pdf")
            self.assertGreaterEqual(d["origem"]["pagina_fim"], d["origem"]["pagina_inicio"])


if __name__ == "__main__":
    unittest.main()
