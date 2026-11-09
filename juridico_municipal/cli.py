"""Linha de comando.

    python -m juridico_municipal municipios
    python -m juridico_municipal buscar --municipios SOBRAL,CRATO
    python -m juridico_municipal buscar --todos --anos 2021-2025 --meses 11
"""

from __future__ import annotations

import argparse
import csv
import sys
import unicodedata
from datetime import date
from pathlib import Path

from .analise import Criterios, apurar
from .api import ClienteSIM
from .coleta import coletar_municipio
from .relatorios import brl, gerar_tudo

PORTAIS_CSV = Path(__file__).parent / "dados" / "portais_transparencia.csv"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").split())


def carregar_portais(caminho: Path = PORTAIS_CSV) -> dict[str, str]:
    if not caminho.exists():
        return {}
    out = {}
    with caminho.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("url_portal_transparencia"):
                out[r["nome_municipio"].upper()] = r["url_portal_transparencia"].strip()
    return out


def _anos(txt: str | None, hoje: date) -> list[int]:
    if not txt:
        return list(range(hoje.year - 5, hoje.year + 1))
    if "-" in txt:
        a, b = txt.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in txt.split(",")]


def cmd_municipios(args) -> int:
    cli = ClienteSIM(cache_dir=args.cache)
    for m in sorted(cli.municipios(), key=lambda x: x["nome_municipio"]):
        print(f"{m['codigo_municipio']}\t{m['codigo_municipio_ibge']}\t{m['nome_municipio']}")
    return 0


def cmd_buscar(args) -> int:
    hoje = date.fromisoformat(args.data_base) if args.data_base else date.today()
    cli = ClienteSIM(cache_dir=args.cache, usar_cache=not args.sem_cache)
    todos = cli.municipios()
    if args.todos:
        alvo = todos
    elif args.municipios:
        pedidos = [_norm(x) for x in args.municipios.split(",") if x.strip()]
        alvo = []
        for p in pedidos:
            achou = [m for m in todos if _norm(m["nome_municipio"]) == p or m["codigo_municipio"] == p
                     or m["codigo_municipio_ibge"] == p]
            if not achou:
                print(f"Município não encontrado: {p}. Use o comando 'municipios' para ver a lista.", file=sys.stderr)
                return 2
            alvo.extend(achou)
    else:
        print("Informe --municipios NOME1,NOME2 ou --todos.", file=sys.stderr)
        return 2

    anos = _anos(args.anos, hoje)
    # os exercícios seguintes são coletados para achar relançamentos e DEA que quitaram os débitos
    coletar_anos = list(range(min(anos), hoje.year + 1))
    print(f"Débitos dos exercícios {anos[0]}–{anos[-1]} (coleta {coletar_anos[0]}–{coletar_anos[-1]}); "
          f"{len(alvo)} município(s).", file=sys.stderr)
    coletados = []
    for i, m in enumerate(alvo, 1):
        print(f"[{i}/{len(alvo)}] {m['nome_municipio']}", file=sys.stderr)
        d = coletar_municipio(cli, m["codigo_municipio"], m["nome_municipio"], coletar_anos, hoje=hoje,
                              workers=args.workers, verbose=not args.quieto)
        if d.erros:
            print(f"  {len(d.erros)} consulta(s) com erro; ex.: {d.erros[0][:200]}", file=sys.stderr)
        coletados.append(d)

    crit = Criterios(
        meses_minimo=args.meses, data_base=hoje, valor_minimo=args.valor_minimo,
        incluir_nao_processados=args.nao_processados, incluir_pessoa_fisica=args.pessoa_fisica,
        todos_elementos=args.todos_elementos, exercicios=set(anos),
    )
    credores, resumo = apurar(coletados, crit)
    arquivos = gerar_tudo(Path(args.saida), credores, resumo, crit, carregar_portais(),
                          max_dossies=args.dossies)
    total = sum(c.total for c in credores)
    print(f"\n{len(credores)} credores com {brl(total)} em aberto há mais de {args.meses} meses.")
    for c in credores[:10]:
        print(f"  {brl(c.total):>18}  {c.nome[:60]}  ({', '.join(c.municipios_devedores)[:60]})")
    print(f"\nRequisições à API: {cli.requisicoes}. Arquivos:")
    for nome, p in arquivos.items():
        print(f"  {p}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="juridico_municipal",
                                 description="Radar de credores de municípios do Ceará (SIM/TCE-CE)")
    ap.add_argument("--cache", default=".cache", help="pasta do cache local (padrão .cache)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("municipios", help="lista os municípios e seus códigos no TCE-CE")

    b = sub.add_parser("buscar", help="coleta os dados e gera os relatórios")
    b.add_argument("--municipios", help="nomes ou códigos separados por vírgula (ex.: SOBRAL,CRATO)")
    b.add_argument("--todos", action="store_true", help="todos os 184 municípios")
    b.add_argument("--anos", help="exercícios dos empenhos, ex.: 2021-2025 (padrão: últimos 5 anos e o atual)")
    b.add_argument("--meses", type=int, default=11, help="atraso mínimo em meses (padrão 11)")
    b.add_argument("--valor-minimo", type=float, default=1000.0, help="total mínimo por credor (padrão R$ 1.000)")
    b.add_argument("--nao-processados", action="store_true",
                   help="incluir empenhado e não liquidado (restos a pagar não processados)")
    b.add_argument("--pessoa-fisica", action="store_true", help="incluir credores pessoas físicas (CPF)")
    b.add_argument("--todos-elementos", action="store_true",
                   help="não filtrar por elemento de despesa de fornecedores/prestadores")
    b.add_argument("--data-base", help="data-base AAAA-MM-DD (padrão: hoje)")
    b.add_argument("--saida", default="saida", help="pasta dos relatórios (padrão saida)")
    b.add_argument("--dossies", type=int, default=300, help="quantos dossiês individuais gerar (padrão 300)")
    b.add_argument("--workers", type=int, default=16, help="consultas simultâneas à API (padrão 16)")
    b.add_argument("--sem-cache", action="store_true", help="ignorar o cache local")
    b.add_argument("--quieto", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "municipios":
        return cmd_municipios(args)
    return cmd_buscar(args)
