import unittest

from enade import indice


class TestIndice(unittest.TestCase):
    def test_estrutura(self):
        d = indice.definicao()
        s, m = d["settings"], d["mappings"]
        self.assertEqual(m["dynamic"], "strict")
        self.assertIn("pt_busca", s["analysis"]["analyzer"])
        self.assertIn("pt_sinonimos", s["analysis"]["analyzer"]["pt_busca"]["filter"])
        self.assertNotIn("pt_sinonimos", s["analysis"]["analyzer"]["pt_indexacao"]["filter"])
        self.assertEqual(s["analysis"]["filter"]["pt_stemmer"]["language"], "brazilian")
        self.assertIn("etica, moral, deontologia", s["analysis"]["filter"]["pt_sinonimos"]["synonyms"])

    def test_campos_obrigatorios_rf(self):
        props = indice.definicao()["mappings"]["properties"]
        for campo in ["area", "curso", "ano", "tipo_prova", "tipo_questao", "competencias",
                      "objetos_conhecimento", "origem", "anulada", "texto_completo"]:
            self.assertIn(campo, props)

    def test_sinonimos_sem_stopwords(self):
        regras = indice.carregar_sinonimos()
        self.assertGreater(len(regras), 0)

    def test_validador_rejeita_stopword(self):
        with self.assertRaises(ValueError):
            indice.validar_regras(["tecnologia da informacao, ti"])


if __name__ == "__main__":
    unittest.main()
