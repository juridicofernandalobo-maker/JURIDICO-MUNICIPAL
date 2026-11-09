from datetime import date

from juridico_municipal.analise import Criterios, apurar, montar_empenhos, subtrair_meses
from juridico_municipal.coleta import DadosMunicipio, meses, tarefas
from juridico_municipal.api import ref_fechada


def _emp(num, data, valor, doc="12345678000199", nome="FORNECEDOR LTDA", elemento="33903900",
         historico="SERVICOS", ex=2024, tipo="1"):
    return {
        "codigo_municipio": "999", "exercicio_orcamento": ex * 100, "codigo_orgao": "01",
        "codigo_unidade_orcamentaria": "01  ", "data_emissao_empenho": f"{data}T00:00:00",
        "numero_empenho": num, "valor_empenhado": valor, "numero_documento_negociante": doc,
        "codigo_tipo_negociante": tipo, "nome_negociante": nome, "codigo_elemento_despesa": elemento,
        "descricao_historico_empenho": historico, "municipio_negociante": "Fortaleza", "codigo_uf": "CE",
    }


def _liq(num, data_emp, data, valor, ex=2024, estornado=False):
    return {"exercicio_orcamento": ex * 100, "codigo_orgao": "01", "codigo_unidade_orcamentaria": "01  ",
            "data_emissao_empenho": f"{data_emp}T00:00:00", "numero_empenho": num,
            "data_liquidacao": f"{data}T00:00:00", "valor_liquidado": valor,
            "numero_sub_empenho_liquidacao": data, "status_estornado": estornado}


def _pag(num, data_emp, data, valor, nota, ex=2024):
    return {"exercicio_orcamento": ex * 100, "codigo_orgao": "01", "codigo_unidade_orcamentaria": "01  ",
            "data_emissao_empenho": f"{data_emp}T00:00:00", "numero_empenho": num,
            "numero_nota_pagamento": nota, "numero_sub_empenho": "001",
            "data_nota_pagamento": f"{data}T00:00:00", "valor_nota_pagamento": valor, "estado_de_estornado": 0}


def _dados(**kw):
    d = DadosMunicipio(codigo="999", nome="TESTE", exercicios=[2024, 2025])
    for k, v in kw.items():
        setattr(d, k, v)
    return d


CRIT = Criterios(meses_minimo=11, data_base=date(2026, 11, 9), valor_minimo=0)


def test_liquidado_nao_pago_ha_mais_de_11_meses():
    d = _dados(empenhos=[_emp("00000001", "2024-03-01", 10000)],
               liquidacoes=[_liq("00000001", "2024-03-01", "2024-04-10", 10000)],
               pagamentos=[_pag("00000001", "2024-03-01", "2024-05-10", 4000, "P1")])
    credores, resumo = apurar([d], CRIT)
    assert len(credores) == 1
    c = credores[0]
    assert round(c.total_processado, 2) == 6000
    assert c.debitos[0].data_base == date(2024, 4, 10)
    assert resumo[0]["total_em_aberto"] == 6000


def test_fifo_data_da_liquidacao_mais_antiga_em_aberto():
    d = _dados(empenhos=[_emp("1", "2024-01-02", 300)],
               liquidacoes=[_liq("1", "2024-01-02", "2024-01-10", 100),
                            _liq("1", "2024-01-02", "2024-02-10", 100),
                            _liq("1", "2024-01-02", "2024-03-10", 100)],
               pagamentos=[_pag("1", "2024-01-02", "2024-04-01", 150, "P1")])
    e = next(iter(montar_empenhos(d).values()))
    assert e.saldo_processado == 150
    assert e.liquidacao_mais_antiga_aberta == date(2024, 2, 10)


def test_debito_recente_nao_entra():
    d = _dados(empenhos=[_emp("1", "2026-01-05", 5000, ex=2026)],
               liquidacoes=[_liq("1", "2026-01-05", "2026-02-01", 5000, ex=2026)])
    credores, _ = apurar([d], CRIT)
    assert credores == []


def test_estorno_de_liquidacao_e_ignorado():
    d = _dados(empenhos=[_emp("1", "2024-01-02", 5000)],
               liquidacoes=[_liq("1", "2024-01-02", "2024-01-10", 5000, estornado=True)])
    credores, _ = apurar([d], CRIT)
    assert credores == []


def test_folha_orgao_publico_e_pessoa_fisica_excluidos():
    d = _dados(
        empenhos=[_emp("1", "2024-01-02", 5000, nome="INSS - INSTITUTO NACIONAL DO SEGURO SOCIAL"),
                  _emp("2", "2024-01-02", 5000, elemento="31901100", doc="98765432000111"),
                  _emp("3", "2024-01-02", 5000, tipo="2", doc="hash", nome="FULANO")],
        liquidacoes=[_liq(n, "2024-01-02", "2024-01-10", 5000) for n in ("1", "2", "3")])
    credores, _ = apurar([d], CRIT)
    assert credores == []
    crit_pf = Criterios(meses_minimo=11, data_base=date(2026, 11, 9), valor_minimo=0, incluir_pessoa_fisica=True)
    credores, _ = apurar([d], crit_pf)
    assert [c.nome for c in credores] == ["FULANO"]


def test_relancamento_no_exercicio_seguinte_quita_o_antigo():
    d = _dados(
        empenhos=[_emp("01020003", "2024-02-01", 8000),
                  _emp("05010001", "2025-01-05", 8000, ex=2025,
                       historico="RELANCAMENTO DE EMPENHO 01020003 EM ATENDIMENTO A LEI")],
        liquidacoes=[_liq("01020003", "2024-02-01", "2024-03-01", 8000),
                     _liq("05010001", "2025-01-05", "2025-01-20", 8000, ex=2025)],
        pagamentos=[_pag("05010001", "2025-01-05", "2025-02-01", 8000, "P9", ex=2025)])
    credores, _ = apurar([d], CRIT)
    assert credores == []


def test_pagamento_lancado_em_outro_empenho_do_mesmo_credor():
    d = _dados(
        empenhos=[_emp("1", "2024-02-01", 5000), _emp("2", "2024-03-01", 5000)],
        liquidacoes=[_liq("1", "2024-02-01", "2024-02-10", 5000)],
        pagamentos=[_pag("2", "2024-03-01", "2024-03-20", 5000, "P2")])
    credores, _ = apurar([d], CRIT)
    assert credores == []


def test_nao_processado_so_com_opcao():
    d = _dados(empenhos=[_emp("1", "2024-02-01", 5000)])
    assert apurar([d], CRIT)[0] == []
    crit = Criterios(meses_minimo=11, data_base=date(2026, 11, 9), valor_minimo=0, incluir_nao_processados=True)
    credores, _ = apurar([d], crit)
    assert credores[0].total_nao_processado == 5000


def test_alerta_art_42_lrf():
    d = _dados(empenhos=[_emp("1", "2024-09-01", 5000)],
               liquidacoes=[_liq("1", "2024-09-01", "2024-09-10", 5000)])
    credores, _ = apurar([d], CRIT)
    assert any("art. 42" in a for a in credores[0].debitos[0].empenho.alertas)


def test_utilitarios_de_data():
    assert subtrair_meses(date(2026, 11, 9), 11) == date(2025, 12, 9)
    assert subtrair_meses(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert meses(2024, 11, 2025, 2) == [202411, 202412, 202501, 202502]
    assert ref_fechada(202401, date(2026, 11, 9))
    assert not ref_fechada(202610, date(2026, 11, 9))
    t = tarefas([2025], date(2026, 2, 15))
    assert ("notas_empenhos", 2025, 202512) in t and ("notas_empenhos", 2025, 202601) not in t
    assert ("notas_pagamentos", 2025, 202602) in t
