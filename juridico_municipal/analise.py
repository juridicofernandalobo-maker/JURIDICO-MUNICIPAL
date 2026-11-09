"""Apuração dos débitos em aberto por empenho e consolidação por credor.

Para cada nota de empenho do SIM:

    empenhado      = valor_empenhado
    anulado        = soma das notas de anulação (inclusive cancelamento de restos a pagar)
    liquidado      = soma das liquidações não estornadas
    pago           = soma das notas de pagamento não estornadas

    saldo processado     = liquidado - pago
        (despesa liquidada e não paga: o fornecedor entregou e a Administração
         atestou, art. 63 da Lei 4.320/64; é o débito mais forte)
    saldo não processado = empenhado - anulado - liquidado
        (empenhado e não liquidado: depende de prova da entrega)

A idade do débito processado é contada da liquidação mais antiga ainda não paga
(os pagamentos quitam as liquidações na ordem cronológica, art. 141 da Lei 14.133/21).
A do não processado é contada da emissão do empenho.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .coleta import DadosMunicipio

TIPO_DOC = {"1": "CNPJ", "2": "CPF", "6": "Folha", "7": "Outro"}

# Elementos de despesa típicos de fornecedores e prestadores de serviço
# (posições 5-6 do código de natureza da despesa, ex.: 33903900 -> 39).
ELEMENTOS_FORNECEDORES = {
    "30": "Material de consumo",
    "31": "Premiações, bens para distribuição",
    "32": "Material, bem ou serviço para distribuição gratuita",
    "33": "Passagens e despesas com locomoção",
    "35": "Serviços de consultoria",
    "36": "Outros serviços de terceiros – pessoa física",
    "37": "Locação de mão de obra",
    "39": "Outros serviços de terceiros – pessoa jurídica",
    "40": "Serviços de tecnologia da informação",
    "51": "Obras e instalações",
    "52": "Equipamentos e material permanente",
    "92": "Despesas de exercícios anteriores",
}

# Credores que não são fornecedores privados (órgãos públicos, encargos, consignações).
EXCLUIR_NOMES = re.compile(
    r"\b(FUNDO\s+(NACIONAL|MUNICIPAL|ESTADUAL)|INSS|INSTITUTO NACIONAL DO SEGURO|RECEITA FEDERAL|"
    r"SECRETARIA\s+(DA|DE|DO)\b|PREFEITURA|C[AÂ]MARA MUNICIPAL|MUNIC[IÍ]PIO DE|ESTADO DO|"
    r"TRIBUNAL|MINIST[EÉ]RIO|FOPAG|FOLHA DE PAGAMENTO|PREVID[EÊ]NCIA|CONS[OÓ]RCIO (P[UÚ]BLICO|INTERMUNICIPAL|DE GEST[AÃ]O)|"
    r"PASEP|FGTS|APRECE|SINDICATO)\b"
)

TOL = 0.01


def _d(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s[:10])


def subtrair_meses(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) - n
    ano, mes = divmod(total, 12)
    mes += 1
    # último dia válido do mês
    for dia in (d.day, 30, 29, 28):
        try:
            return date(ano, mes, dia)
        except ValueError:
            continue
    raise ValueError(d)


def meses_entre(inicio: date, fim: date) -> int:
    m = (fim.year - inicio.year) * 12 + fim.month - inicio.month
    if fim.day < inicio.day:
        m -= 1
    return m


@dataclass
class Empenho:
    municipio: str
    municipio_nome: str
    exercicio: int
    orgao: str
    unidade: str
    numero: str
    data_emissao: date
    credor_doc: str
    credor_tipo: str
    credor_nome: str
    credor_municipio: str
    credor_uf: str
    credor_endereco: str
    credor_fone: str
    elemento: str
    historico: str
    modalidade: str
    licitacao: str
    contrato: str
    data_contrato: str
    empenhado: float
    anulado: float = 0.0
    liquidado: float = 0.0
    pago: float = 0.0
    compensado: float = 0.0  # quitado por relançamento/DEA/reconhecimento em exercício posterior
    compensacoes: list[str] = field(default_factory=list)
    liquidacoes: list[tuple[date, float]] = field(default_factory=list)
    pagamentos: list[tuple[date, float]] = field(default_factory=list)
    anulacoes: list[tuple[date, float, str]] = field(default_factory=list)

    # calculados
    saldo_processado: float = 0.0
    saldo_nao_processado: float = 0.0
    liquidacao_mais_antiga_aberta: date | None = None
    ultimo_pagamento: date | None = None
    alertas: list[str] = field(default_factory=list)

    @property
    def chave(self):
        return (self.municipio, self.exercicio, self.orgao, self.unidade, self.data_emissao, self.numero)

    @property
    def elemento_cod(self) -> str:
        return self.elemento[4:6] if len(self.elemento) >= 6 else ""

    def calcular(self) -> None:
        pago_ef = self.pago + self.compensado
        self.saldo_processado = max(0.0, self.liquidado - pago_ef)
        excesso_comp = max(0.0, pago_ef - max(self.liquidado, self.pago))
        self.saldo_nao_processado = max(0.0, self.empenhado - self.anulado - self.liquidado - excesso_comp)
        # FIFO: os pagamentos quitam as liquidações mais antigas primeiro
        restante_pago = pago_ef
        self.liquidacao_mais_antiga_aberta = None
        for dt, valor in sorted(self.liquidacoes):
            if restante_pago >= valor - TOL:
                restante_pago -= valor
                continue
            self.liquidacao_mais_antiga_aberta = dt
            break
        if self.pagamentos:
            self.ultimo_pagamento = max(d for d, _ in self.pagamentos)
        self.alertas = []
        anulado_sobre_liquidado = self.anulado - (self.empenhado - self.liquidado)
        if anulado_sobre_liquidado > TOL and self.saldo_processado > TOL:
            self.alertas.append(
                "Anulação/cancelamento alcançou valor já liquidado e não pago "
                f"(R$ {anulado_sobre_liquidado:,.2f}): possível cancelamento de resto a pagar processado"
            )
        self.alertas.extend(self.compensacoes)
        if self.pago - self.liquidado > TOL:
            self.alertas.append("Pago maior que o liquidado no SIM: conferir no portal do município")
        if self.exercicio in (2020, 2024, 2028) and self.data_emissao >= date(self.exercicio, 5, 1):
            self.alertas.append(
                "Despesa contraída nos dois últimos quadrimestres do mandato (art. 42 da LRF)"
            )


@dataclass
class Debito:
    empenho: Empenho
    categoria: str  # "processado" | "nao_processado"
    valor: float
    data_base: date
    meses_em_aberto: int


@dataclass
class Credor:
    chave: str
    doc: str
    tipo: str
    nome: str
    municipio: str
    uf: str
    endereco: str
    fone: str
    debitos: list[Debito] = field(default_factory=list)

    @property
    def total_processado(self) -> float:
        return sum(d.valor for d in self.debitos if d.categoria == "processado")

    @property
    def total_nao_processado(self) -> float:
        return sum(d.valor for d in self.debitos if d.categoria == "nao_processado")

    @property
    def total(self) -> float:
        return self.total_processado + self.total_nao_processado

    @property
    def municipios_devedores(self) -> list[str]:
        return sorted({d.empenho.municipio_nome for d in self.debitos})

    @property
    def data_mais_antiga(self) -> date:
        return min(d.data_base for d in self.debitos)

    @property
    def maior_atraso_meses(self) -> int:
        return max(d.meses_em_aberto for d in self.debitos)


def _limpo(v) -> str:
    s = (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v))
    return "" if set(s) <= {"*"} else s


def montar_empenhos(dados: DadosMunicipio) -> dict[tuple, Empenho]:
    emp: dict[tuple, Empenho] = {}
    for r in dados.empenhos:
        e = Empenho(
            municipio=dados.codigo,
            municipio_nome=dados.nome,
            exercicio=int(r["exercicio_orcamento"]) // 100,
            orgao=(r.get("codigo_orgao") or "").strip(),
            unidade=(r.get("codigo_unidade_orcamentaria") or "").strip(),
            numero=(r.get("numero_empenho") or "").strip(),
            data_emissao=_d(r["data_emissao_empenho"]),
            credor_doc=_limpo(r.get("numero_documento_negociante")),
            credor_tipo=TIPO_DOC.get(str(r.get("codigo_tipo_negociante")), "Outro"),
            credor_nome=_limpo(r.get("nome_negociante")).upper(),
            credor_municipio=_limpo(r.get("municipio_negociante")),
            credor_uf=_limpo(r.get("codigo_uf")),
            credor_endereco=_limpo(r.get("endereco_negociante")),
            credor_fone=_limpo(r.get("fone_negociante")),
            elemento=(r.get("codigo_elemento_despesa") or "").strip(),
            historico=_limpo(r.get("descricao_historico_empenho")),
            modalidade=_limpo(r.get("modalidade_nota_empenho")),
            licitacao=_limpo(r.get("numero_licitacao")),
            contrato=_limpo(r.get("numero_contrato")),
            data_contrato=_limpo(r.get("data_contrato"))[:10],
            empenhado=float(r.get("valor_empenhado") or 0),
        )
        emp.setdefault(e.chave, e)

    def chave_mov(r, campo_num):
        return (
            dados.codigo,
            int(r["exercicio_orcamento"]) // 100,
            (r.get("codigo_orgao") or "").strip(),
            (r.get("codigo_unidade_orcamentaria") or "").strip(),
            _d(r["data_emissao_empenho"]),
            (r.get(campo_num) or "").strip(),
        )

    vistos = set()
    for r in dados.liquidacoes:
        if r.get("status_estornado"):
            continue
        k = chave_mov(r, "numero_empenho")
        id_ = ("L", k, r.get("numero_sub_empenho_liquidacao"), r.get("data_liquidacao"), r.get("valor_liquidado"))
        if k not in emp or id_ in vistos:
            continue
        vistos.add(id_)
        v = float(r.get("valor_liquidado") or 0)
        emp[k].liquidado += v
        emp[k].liquidacoes.append((_d(r["data_liquidacao"]), v))

    for r in dados.pagamentos:
        if r.get("estado_de_estornado"):
            continue
        k = chave_mov(r, "numero_empenho")
        id_ = ("P", k, r.get("numero_nota_pagamento"), r.get("numero_sub_empenho"))
        if k not in emp or id_ in vistos:
            continue
        vistos.add(id_)
        v = float(r.get("valor_nota_pagamento") or 0)
        emp[k].pago += v
        emp[k].pagamentos.append((_d(r.get("data_nota_pagamento")) or emp[k].data_emissao, v))

    for r in dados.anulacoes:
        k = chave_mov(r, "numero_nota_empenho")
        id_ = ("A", k, r.get("numero_nota_anulacao"))
        if k not in emp or id_ in vistos:
            continue
        vistos.add(id_)
        v = float(r.get("valor_anulacao") or 0)
        emp[k].anulado += v
        emp[k].anulacoes.append((_d(r.get("data_anulacao")), v, _limpo(r.get("descricao_anulacao"))))

    for e in emp.values():
        e.calcular()
    return emp


RE_REGULARIZACAO = re.compile(
    r"RELAN.{0,2}AMENTO|EXERC.{0,2}CIOS? ANTERIOR|RECONHECIMENTO DE D.{0,2}VIDA|RESTOS? A PAGAR|\bDEA\b|"
    r"FORA DO EXERC"
)


def _chave_credor(e: Empenho) -> str:
    return e.credor_doc if e.credor_tipo == "CNPJ" and e.credor_doc else f"{e.credor_tipo}:{e.credor_nome}"


def compensar_regularizacoes(emp: dict[tuple, Empenho]) -> None:
    """Abate dos débitos antigos os empenhos posteriores que os substituíram.

    Municípios costumam quitar restos a pagar cancelados emitindo novo empenho no ano
    seguinte (relançamento, despesa de exercício anterior – elemento 92 – ou
    reconhecimento de dívida). O valor do novo empenho é abatido:

    1. do empenho antigo do mesmo credor cujo número aparece no histórico; e,
    2. o que sobrar, dos débitos mais antigos do mesmo credor em exercícios anteriores.

    O novo empenho segue sendo analisado por conta própria (se não for pago, vira débito).
    """
    por_credor: dict[str, list[Empenho]] = {}
    for e in emp.values():
        por_credor.setdefault(_chave_credor(e), []).append(e)
    for lista in por_credor.values():
        regs = [r for r in lista if r.elemento_cod == "92" or RE_REGULARIZACAO.search(r.historico.upper())]
        if not regs:
            continue
        for r in sorted(regs, key=lambda x: x.data_emissao):
            valor = max(0.0, r.empenhado - r.anulado)
            if valor <= TOL:
                continue
            antigos = [e for e in lista if e is not r and e.exercicio < r.exercicio
                       and (e.saldo_processado + e.saldo_nao_processado) > TOL]
            if not antigos:
                continue
            numeros = re.findall(r"\d{6,}", r.historico)
            citados = [e for e in antigos if e.numero and any(e.numero in n for n in numeros)]
            restantes = sorted((e for e in antigos if e not in citados), key=lambda e: e.data_emissao)
            for e in citados + restantes:
                if valor <= TOL:
                    break
                aberto = e.saldo_processado + e.saldo_nao_processado
                abate = min(aberto, valor)
                e.compensado += abate
                valor -= abate
                forma = "citado no histórico" if e in citados else "mesmo credor, sem citação do número"
                e.compensacoes.append(
                    f"R$ {abate:,.2f} abatidos pelo empenho {r.numero}/{r.exercicio} "
                    f"(relançamento/DEA, {forma}): conferir"
                )
                e.calcular()


def conciliar_por_credor(emp: dict[tuple, Empenho]) -> None:
    """Abate pagamentos lançados acima do liquidado em outros empenhos do mesmo credor.

    No SIM é comum o pagamento ser registrado em um empenho e a liquidação em outro
    (empenho global x estimativo, troca de fonte). Se, para o mesmo credor, um empenho
    tem pago > liquidado, esse excesso quita débitos abertos do mesmo exercício ou de
    exercícios anteriores, do mais antigo para o mais novo.
    """
    por_credor: dict[str, list[Empenho]] = {}
    for e in emp.values():
        por_credor.setdefault(_chave_credor(e), []).append(e)
    for lista in por_credor.values():
        sobras = sorted(
            ((e, e.pago - e.liquidado) for e in lista if e.pago - e.liquidado > TOL),
            key=lambda x: x[0].data_emissao,
        )
        if not sobras:
            continue
        abertos = sorted((e for e in lista if e.saldo_processado > TOL), key=lambda e: e.data_emissao)
        for origem, valor in sobras:
            for e in abertos:
                if valor <= TOL:
                    break
                if e.exercicio > origem.exercicio or e.saldo_processado <= TOL:
                    continue
                abate = min(e.saldo_processado, valor)
                e.compensado += abate
                valor -= abate
                e.compensacoes.append(
                    f"R$ {abate:,.2f} abatidos por pagamento lançado acima do liquidado no empenho "
                    f"{origem.numero}/{origem.exercicio} do mesmo credor: conferir"
                )
                e.calcular()


@dataclass
class Criterios:
    meses_minimo: int = 11
    data_base: date = field(default_factory=date.today)
    valor_minimo: float = 1000.0
    incluir_nao_processados: bool = False
    incluir_pessoa_fisica: bool = False
    todos_elementos: bool = False
    exercicios: set[int] | None = None  # exercícios dos débitos reportados (None = todos os coletados)

    @property
    def data_limite(self) -> date:
        return subtrair_meses(self.data_base, self.meses_minimo)


def credor_elegivel(e: Empenho, c: Criterios) -> bool:
    if e.credor_tipo == "CNPJ":
        pass
    elif e.credor_tipo == "CPF":
        if not c.incluir_pessoa_fisica:
            return False
    else:
        return False
    if not c.todos_elementos and e.elemento_cod not in ELEMENTOS_FORNECEDORES:
        return False
    if EXCLUIR_NOMES.search(e.credor_nome):
        return False
    return True


def debitos_do_empenho(e: Empenho, c: Criterios) -> list[Debito]:
    out = []
    if c.exercicios is not None and e.exercicio not in c.exercicios:
        return out
    limite = c.data_limite
    if e.saldo_processado > TOL and e.liquidacao_mais_antiga_aberta and e.liquidacao_mais_antiga_aberta < limite:
        out.append(
            Debito(e, "processado", round(e.saldo_processado, 2), e.liquidacao_mais_antiga_aberta,
                   meses_entre(e.liquidacao_mais_antiga_aberta, c.data_base))
        )
    if c.incluir_nao_processados and e.saldo_nao_processado > TOL and e.data_emissao < limite:
        out.append(
            Debito(e, "nao_processado", round(e.saldo_nao_processado, 2), e.data_emissao,
                   meses_entre(e.data_emissao, c.data_base))
        )
    return out


def apurar(lista_dados: list[DadosMunicipio], c: Criterios) -> tuple[list[Credor], list[dict]]:
    credores: dict[str, Credor] = {}
    resumo_municipios = []
    for dados in lista_dados:
        emp = montar_empenhos(dados)
        conciliar_por_credor(emp)
        compensar_regularizacoes(emp)
        total_mun = 0.0
        credores_mun = set()
        for e in emp.values():
            if not credor_elegivel(e, c):
                continue
            for d in debitos_do_empenho(e, c):
                chave = _chave_credor(e)
                cr = credores.get(chave)
                if cr is None:
                    cr = credores[chave] = Credor(
                        chave=chave, doc=e.credor_doc if e.credor_tipo == "CNPJ" else "",
                        tipo=e.credor_tipo, nome=e.credor_nome, municipio=e.credor_municipio,
                        uf=e.credor_uf, endereco=e.credor_endereco, fone=e.credor_fone,
                    )
                cr.debitos.append(d)
                total_mun += d.valor
                credores_mun.add(chave)
        resumo_municipios.append({
            "codigo_tce": dados.codigo,
            "municipio": dados.nome,
            "exercicios": f"{min(dados.exercicios)}-{max(dados.exercicios)}",
            "empenhos_analisados": len(emp),
            "credores_com_debito": len(credores_mun),
            "total_em_aberto": round(total_mun, 2),
            "ultimo_mes_enviado_sim": dados.ultimo_mes_enviado,
            "erros_consulta": len(dados.erros),
        })
    lista = [cr for cr in credores.values() if cr.total >= c.valor_minimo]
    lista.sort(key=lambda cr: (-cr.total_processado, -cr.total))
    return lista, resumo_municipios


def prioridade(cr: Credor) -> str:
    """Classificação simples para triagem da carteira."""
    if cr.total_processado >= 100_000 or (cr.total_processado >= 30_000 and cr.maior_atraso_meses >= 24):
        return "A"
    if cr.total_processado >= 20_000:
        return "B"
    return "C"
