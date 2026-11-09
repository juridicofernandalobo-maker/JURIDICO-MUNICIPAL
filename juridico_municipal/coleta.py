"""Coleta, por município, das tabelas do SIM necessárias para apurar os débitos."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date

from .api import ClienteSIM, ErroAPI

# Tabelas consultadas e em quais meses de referência.
# Empenhos: só nos meses do próprio exercício.
# Liquidações, pagamentos e anulações: do início do exercício até hoje, porque os
# restos a pagar são liquidados, pagos ou cancelados nos exercícios seguintes.
TABELA_EMPENHOS = "notas_empenhos"
TABELAS_MOVIMENTO = ("liquidacoes", "notas_pagamentos", "notas_anulacoes_empenhos")


def meses(ano_ini: int, mes_ini: int, ano_fim: int, mes_fim: int) -> list[int]:
    out = []
    a, m = ano_ini, mes_ini
    while (a, m) <= (ano_fim, mes_fim):
        out.append(a * 100 + m)
        m += 1
        if m == 13:
            a, m = a + 1, 1
    return out


@dataclass
class DadosMunicipio:
    codigo: str
    nome: str
    exercicios: list[int]
    empenhos: list[dict] = field(default_factory=list)
    liquidacoes: list[dict] = field(default_factory=list)
    pagamentos: list[dict] = field(default_factory=list)
    anulacoes: list[dict] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)
    ultimo_mes_enviado: int | None = None  # último AAAAMM com pagamentos ou empenhos


def tarefas(exercicios: list[int], hoje: date) -> list[tuple[str, int, int]]:
    out = []
    for ex in exercicios:
        for ref in meses(ex, 1, ex, 12):
            if ref <= hoje.year * 100 + hoje.month:
                out.append((TABELA_EMPENHOS, ex, ref))
        for ref in meses(ex, 1, hoje.year, hoje.month):
            for t in TABELAS_MOVIMENTO:
                out.append((t, ex, ref))
    return out


def coletar_municipio(
    cliente: ClienteSIM,
    codigo: str,
    nome: str,
    exercicios: list[int],
    hoje: date | None = None,
    workers: int = 8,
    verbose: bool = True,
) -> DadosMunicipio:
    hoje = hoje or date.today()
    dados = DadosMunicipio(codigo=codigo, nome=nome, exercicios=list(exercicios))
    lista = tarefas(exercicios, hoje)
    destino = {
        TABELA_EMPENHOS: dados.empenhos,
        "liquidacoes": dados.liquidacoes,
        "notas_pagamentos": dados.pagamentos,
        "notas_anulacoes_empenhos": dados.anulacoes,
    }
    feitos = 0
    ultimo = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {
            pool.submit(cliente.mensal, t, codigo, ex, ref): (t, ex, ref) for t, ex, ref in lista
        }
        for f in as_completed(futuros):
            t, ex, ref = futuros[f]
            feitos += 1
            try:
                regs = f.result()
            except ErroAPI as e:
                dados.erros.append(str(e))
                continue
            destino[t].extend(regs)
            if regs and t in (TABELA_EMPENHOS, "notas_pagamentos"):
                ultimo = max(ultimo, ref)
            if verbose and feitos % 50 == 0:
                print(f"  {nome}: {feitos}/{len(lista)} consultas", file=sys.stderr)
    dados.ultimo_mes_enviado = ultimo or None
    return dados
