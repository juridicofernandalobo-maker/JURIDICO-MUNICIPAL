"""Saídas: planilhas CSV/XLSX, painel HTML e dossiê por credor."""

from __future__ import annotations

import csv
import html
import json
import re
from datetime import date
from pathlib import Path

from .analise import ELEMENTOS_FORNECEDORES, Credor, Criterios, prioridade

FUNDAMENTOS = [
    ("Lei 4.320/1964, arts. 58 a 64",
     "Empenho, liquidação e pagamento. A liquidação (art. 63) é a verificação do direito adquirido "
     "pelo credor, com base nos documentos que comprovam a entrega ou a execução."),
    ("Lei 4.320/1964, arts. 36 e 37",
     "Despesas empenhadas e não pagas até 31/12 são inscritas em restos a pagar; as de exercícios "
     "encerrados podem ser pagas como despesas de exercícios anteriores (elemento 92)."),
    ("Lei 14.133/2021, art. 141",
     "Pagamentos em ordem cronológica de exigibilidade, por fonte de recurso; alteração só com "
     "justificativa publicada."),
    ("Lei 14.133/2021, art. 137, § 2º, IV",
     "Atraso superior a 2 meses nos pagamentos dá ao contratado direito à extinção do contrato "
     "(art. 137, § 3º, II: opção de suspender a execução)."),
    ("Lei 14.133/2021, art. 92, V; Lei 8.666/1993, art. 40, XIV, 'c' e 'd'",
     "Atualização financeira e compensação por atraso previstas no contrato."),
    ("Lei 8.666/1993, art. 78, XV",
     "Para contratos regidos pela lei antiga: atraso superior a 90 dias autoriza a rescisão ou a "
     "suspensão do cumprimento das obrigações."),
    ("Decreto 20.910/1932, arts. 1º e 4º",
     "Prescrição quinquenal contra a Fazenda Pública; o requerimento administrativo suspende o prazo "
     "enquanto pendente de decisão."),
    ("Súmula 339 do STJ",
     "É cabível ação monitória contra a Fazenda Pública (nota de empenho e liquidação como prova escrita)."),
    ("CF, art. 100",
     "Condenação judicial é paga por precatório ou RPV; o reconhecimento administrativo da dívida "
     "evita essa fila."),
    ("LRF (LC 101/2000), art. 42",
     "Vedado ao titular do Poder contrair, nos dois últimos quadrimestres do mandato, obrigação que "
     "não possa ser paga no mandato sem disponibilidade de caixa para o exercício seguinte."),
]

CHECKLIST = [
    "Notas de empenho e de liquidação (portal da transparência do município ou SIM/TCE-CE)",
    "Notas fiscais/faturas atestadas e comprovantes de entrega ou medições",
    "Contrato, aditivos e ata de registro de preços; processo licitatório ou de dispensa",
    "Correspondências e requerimentos de pagamento já protocolados",
    "Certidões de regularidade fiscal do credor na época dos pagamentos",
    "Verificar se houve cancelamento de restos a pagar ou renegociação/parcelamento",
    "Verificar prescrição (5 anos) e causas de suspensão/interrupção",
]

AVISO_ETICO = (
    "Uso profissional: a abordagem de potenciais clientes deve observar o Código de Ética e "
    "Disciplina da OAB (art. 7º e arts. 39 a 47 – vedação à captação de clientela e à "
    "mercantilização) e o Provimento 205/2021 do CFOAB (publicidade informativa e sóbria). "
    "Os dados são públicos (Lei 12.527/2011), mas seu tratamento deve respeitar a LGPD "
    "(Lei 13.709/2018), em especial para credores pessoas físicas."
)


def brl(v: float) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_doc(doc: str) -> str:
    d = re.sub(r"\D", "", doc or "")
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return doc or ""


def fmt_data(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def fmt_ref(ref: int | None) -> str:
    return f"{ref % 100:02d}/{ref // 100}" if ref else "sem envio"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60] or "credor"


def linhas_debitos(credores: list[Credor]) -> list[dict]:
    out = []
    for cr in credores:
        for d in sorted(cr.debitos, key=lambda x: x.data_base):
            e = d.empenho
            out.append({
                "credor": cr.nome,
                "cnpj": fmt_doc(cr.doc),
                "tipo_credor": cr.tipo,
                "municipio_devedor": e.municipio_nome,
                "exercicio": e.exercicio,
                "orgao": e.orgao,
                "unidade": e.unidade,
                "empenho": e.numero,
                "data_empenho": fmt_data(e.data_emissao),
                "elemento": e.elemento,
                "natureza": ELEMENTOS_FORNECEDORES.get(e.elemento_cod, ""),
                "categoria": "Liquidado e não pago" if d.categoria == "processado" else "Empenhado e não liquidado",
                "valor_empenhado": round(e.empenhado, 2),
                "valor_anulado": round(e.anulado, 2),
                "valor_liquidado": round(e.liquidado, 2),
                "valor_pago": round(e.pago, 2),
                "valor_em_aberto": d.valor,
                "data_base_atraso": fmt_data(d.data_base),
                "meses_em_aberto": d.meses_em_aberto,
                "ultimo_pagamento": fmt_data(e.ultimo_pagamento),
                "licitacao": e.licitacao,
                "contrato": e.contrato,
                "historico": e.historico,
                "alertas": " | ".join(e.alertas + (
                    ["Mais de 5 anos: verificar prescrição (Decreto 20.910/32)"] if d.meses_em_aberto >= 60 else [])),
            })
    return out


def linhas_credores(credores: list[Credor]) -> list[dict]:
    return [{
        "prioridade": prioridade(cr),
        "credor": cr.nome,
        "cnpj": fmt_doc(cr.doc),
        "tipo_credor": cr.tipo,
        "municipio_sede": cr.municipio,
        "uf": cr.uf,
        "endereco": cr.endereco,
        "telefone": cr.fone,
        "municipios_devedores": "; ".join(cr.municipios_devedores),
        "qtd_empenhos": len({d.empenho.chave for d in cr.debitos}),
        "liquidado_nao_pago": round(cr.total_processado, 2),
        "empenhado_nao_liquidado": round(cr.total_nao_processado, 2),
        "total_em_aberto": round(cr.total, 2),
        "debito_mais_antigo": fmt_data(cr.data_mais_antiga),
        "maior_atraso_meses": cr.maior_atraso_meses,
    } for cr in credores]


def gravar_csv(caminho: Path, linhas: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", newline="", encoding="utf-8-sig") as f:
        if not linhas:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";")
        w.writeheader()
        for l in linhas:
            w.writerow({k: (str(v).replace(".", ",") if isinstance(v, float) else v) for k, v in l.items()})


def gravar_xlsx(caminho: Path, abas: dict[str, list[dict]]) -> bool:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        return False
    wb = Workbook()
    wb.remove(wb.active)
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome[:31])
        if not linhas:
            continue
        cab = list(linhas[0])
        ws.append(cab)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="2A3F7E")
        for l in linhas:
            ws.append([l[k] for k in cab])
        for i, k in enumerate(cab, 1):
            if k.startswith(("valor", "total", "liquidado_", "empenhado_")):
                for (cel,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    cel.number_format = '"R$" #,##0.00'
            largura = min(60, max(10, *(len(str(l[k])) for l in linhas[:200]), len(k)))
            ws.column_dimensions[get_column_letter(i)].width = largura + 2
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)
    return True


# ---------------------------------------------------------------- HTML
CSS = """
:root{--bg:#f6f7fb;--card:#fff;--tx:#1d2433;--mut:#5d6679;--bd:#dfe3ec;--pri:#2a3f7e;--a:#b42318;--b:#b54708;--c:#475467}
@media (prefers-color-scheme: dark){:root{--bg:#11141b;--card:#1a1f2b;--tx:#e8ebf2;--mut:#9aa3b5;--bd:#2c3343;--pri:#8fa6ec;--a:#f97066;--b:#fdb022;--c:#98a2b3}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1280px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}
.mut{color:var(--mut)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px}.card b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--bd);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--card);cursor:pointer;white-space:nowrap}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.p{display:inline-block;min-width:22px;text-align:center;border-radius:6px;font-weight:700;color:#fff;padding:1px 6px}
.pA{background:var(--a)}.pB{background:var(--b)}.pC{background:var(--c)}
.filtros{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.filtros input,.filtros select{padding:7px 9px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx);font:inherit;max-width:100%}
.aviso{background:var(--card);border-left:4px solid var(--b);padding:10px 14px;border-radius:6px;margin:14px 0}
a{color:var(--pri)}ul{padding-left:20px}td.h{min-width:340px}
"""

JS = """
function filtrar(){const q=document.getElementById('q').value.toLowerCase();const m=document.getElementById('mun').value;const p=document.getElementById('pri').value;
document.querySelectorAll('#tc tbody tr').forEach(tr=>{const t=tr.dataset.t;const ok=(!q||t.includes(q))&&(!m||tr.dataset.m.split('|').includes(m))&&(!p||tr.dataset.p===p);tr.style.display=ok?'':'none'})}
document.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{const tb=th.closest('table').tBodies[0];const rows=[...tb.rows];const asc=th.dataset.s!=='1';th.dataset.s=asc?'1':'0';
rows.sort((a,b)=>{const x=a.cells[i].dataset.v??a.cells[i].innerText,y=b.cells[i].dataset.v??b.cells[i].innerText;const nx=parseFloat(x),ny=parseFloat(y);const r=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y,'pt');return asc?r:-r});rows.forEach(r=>tb.appendChild(r))}));
"""


def _pagina(titulo: str, corpo: str) -> str:
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(titulo)}</title>"
            f"<style>{CSS}</style></head><body><main>{corpo}</main><script>{JS}</script></body></html>")


def gravar_painel(caminho: Path, credores: list[Credor], municipios: list[dict], c: Criterios,
                  dossies: dict[str, str]) -> None:
    e = html.escape
    tot_p = sum(cr.total_processado for cr in credores)
    tot_np = sum(cr.total_nao_processado for cr in credores)
    nomes_mun = sorted({m for cr in credores for m in cr.municipios_devedores})
    linhas = []
    for cr in credores:
        pr = prioridade(cr)
        link = dossies.get(cr.chave)
        nome = f"<a href='{e(link)}'>{e(cr.nome)}</a>" if link else e(cr.nome)
        linhas.append(
            f"<tr data-t='{e((cr.nome + ' ' + cr.doc + ' ' + cr.municipio).lower())}' data-m='{e('|'.join(cr.municipios_devedores))}' data-p='{pr}'>"
            f"<td data-v='{pr}'><span class='p p{pr}'>{pr}</span></td><td>{nome}<div class='mut'>{e(fmt_doc(cr.doc) or cr.tipo)} · {e(cr.municipio)}/{e(cr.uf)}</div></td>"
            f"<td>{e(', '.join(cr.municipios_devedores))}</td>"
            f"<td class='n' data-v='{cr.total_processado:.2f}'>{brl(cr.total_processado)}</td>"
            f"<td class='n' data-v='{cr.total_nao_processado:.2f}'>{brl(cr.total_nao_processado)}</td>"
            f"<td class='n' data-v='{len(cr.debitos)}'>{len(cr.debitos)}</td>"
            f"<td class='n' data-v='{cr.maior_atraso_meses}'>{cr.maior_atraso_meses}</td>"
            f"<td data-v='{cr.data_mais_antiga.isoformat()}'>{fmt_data(cr.data_mais_antiga)}</td></tr>")
    lm = []
    lim_envio = c.data_base.year * 100 + c.data_base.month
    for m in sorted(municipios, key=lambda x: -x["total_em_aberto"]):
        ult = m["ultimo_mes_enviado_sim"]
        atraso = ""
        if not ult or (lim_envio // 100 * 12 + lim_envio % 100) - (ult // 100 * 12 + ult % 100) > 3:
            atraso = " ⚠️"
        lm.append(
            f"<tr><td>{e(m['municipio'])}</td><td class='n' data-v='{m['total_em_aberto']}'>{brl(m['total_em_aberto'])}</td>"
            f"<td class='n'>{m['credores_com_debito']}</td><td class='n'>{m['empenhos_analisados']}</td>"
            f"<td data-v='{ult or 0}'>{fmt_ref(ult)}{atraso}</td><td class='n'>{m['erros_consulta']}</td></tr>")
    opts = "".join(f"<option>{e(n)}</option>" for n in nomes_mun)
    corpo = f"""
<h1>Radar de credores – municípios do Ceará</h1>
<div class='mut'>Débitos de fornecedores e prestadores em aberto há mais de {c.meses_minimo} meses
(data-base {fmt_data(c.data_base)}; corte: anterior a {fmt_data(c.data_limite)}). Fonte: SIM/TCE-CE, API de Dados Abertos.</div>
<div class='cards'>
<div class='card'><span class='mut'>Credores</span><b>{len(credores)}</b></div>
<div class='card'><span class='mut'>Liquidado e não pago</span><b>{brl(tot_p)}</b></div>
<div class='card'><span class='mut'>Empenhado e não liquidado</span><b>{brl(tot_np)}</b></div>
<div class='card'><span class='mut'>Municípios analisados</span><b>{len(municipios)}</b></div>
</div>
<div class='aviso'><b>Conferência obrigatória.</b> O SIM reflete o que o município enviou ao TCE-CE. Antes de qualquer
providência, confirme cada empenho no portal da transparência do município e com o credor. Municípios marcados com ⚠️
estão com envio do SIM atrasado: pagamentos recentes podem não constar.</div>
<h2>Credores</h2>
<div class='filtros'><input id='q' placeholder='Buscar nome ou CNPJ' oninput='filtrar()'>
<select id='mun' onchange='filtrar()'><option value=''>Todos os municípios</option>{opts}</select>
<select id='pri' onchange='filtrar()'><option value=''>Todas as prioridades</option><option>A</option><option>B</option><option>C</option></select></div>
<div class='wrap'><table id='tc'><thead><tr><th>Prior.</th><th>Credor</th><th>Municípios devedores</th><th>Liquidado não pago</th>
<th>Empenhado não liquidado</th><th>Débitos</th><th>Maior atraso (meses)</th><th>Mais antigo</th></tr></thead><tbody>{''.join(linhas)}</tbody></table></div>
<h2>Municípios</h2>
<div class='wrap'><table><thead><tr><th>Município</th><th>Total em aberto</th><th>Credores</th><th>Empenhos analisados</th><th>Último envio SIM</th><th>Erros</th></tr></thead>
<tbody>{''.join(lm)}</tbody></table></div>
<p class='mut'>Prioridade A: liquidado não pago ≥ R$ 100 mil, ou ≥ R$ 30 mil com atraso ≥ 24 meses. B: ≥ R$ 20 mil. C: demais.</p>
<div class='aviso'>{e(AVISO_ETICO)}</div>
"""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(_pagina("Radar de credores", corpo), encoding="utf-8")


def gravar_dossie(caminho: Path, cr: Credor, c: Criterios, portais: dict[str, str]) -> None:
    e = html.escape
    linhas = []
    for d in sorted(cr.debitos, key=lambda x: (x.empenho.municipio_nome, x.data_base)):
        emp = d.empenho
        alertas = list(emp.alertas)
        if d.meses_em_aberto >= 60:
            alertas.append("Mais de 5 anos: verificar prescrição")
        linhas.append(
            f"<tr><td>{e(emp.municipio_nome)}</td><td>{emp.exercicio}</td><td>{e(emp.orgao)}.{e(emp.unidade)}</td>"
            f"<td>{e(emp.numero)}<div class='mut'>{fmt_data(emp.data_emissao)}</div></td>"
            f"<td>{e(emp.elemento)}<div class='mut'>{e(ELEMENTOS_FORNECEDORES.get(emp.elemento_cod, ''))}</div></td>"
            f"<td>{'Liquidado e não pago' if d.categoria == 'processado' else 'Empenhado e não liquidado'}</td>"
            f"<td class='n'>{brl(emp.empenhado)}</td><td class='n'>{brl(emp.liquidado)}</td><td class='n'>{brl(emp.pago)}</td>"
            f"<td class='n'><b>{brl(d.valor)}</b></td><td>{fmt_data(d.data_base)}<div class='mut'>{d.meses_em_aberto} meses</div></td>"
            f"<td class='h'>{e(emp.historico[:300])}{'<div class=mut>Contrato ' + e(emp.contrato) + '</div>' if emp.contrato else ''}"
            f"{''.join('<div><b>⚠ ' + e(a) + '</b></div>' for a in alertas)}</td></tr>")
    links = []
    for m in cr.municipios_devedores:
        url = portais.get(m.upper(), "")
        links.append(f"<li>{e(m)}: " + (f"<a href='{e(url)}'>{e(url)}</a>" if url else
                     "<span class='mut'>cadastre o endereço do portal em portais_transparencia.csv</span>") + "</li>")
    fund = "".join(f"<li><b>{e(t)}</b> – {e(x)}</li>" for t, x in FUNDAMENTOS)
    chk = "".join(f"<li>{e(x)}</li>" for x in CHECKLIST)
    corpo = f"""
<p><a href='../painel.html'>← painel</a></p>
<h1>{e(cr.nome)}</h1>
<div class='mut'>{e(fmt_doc(cr.doc) or cr.tipo)} · {e(cr.municipio)}/{e(cr.uf)} {('· ' + e(cr.endereco)) if cr.endereco else ''} {('· ' + e(cr.fone)) if cr.fone else ''}</div>
<div class='cards'>
<div class='card'><span class='mut'>Liquidado e não pago</span><b>{brl(cr.total_processado)}</b></div>
<div class='card'><span class='mut'>Empenhado e não liquidado</span><b>{brl(cr.total_nao_processado)}</b></div>
<div class='card'><span class='mut'>Maior atraso</span><b>{cr.maior_atraso_meses} meses</b></div>
<div class='card'><span class='mut'>Prioridade</span><b>{prioridade(cr)}</b></div>
</div>
<h2>Empenhos em aberto</h2>
<div class='wrap'><table><thead><tr><th>Município</th><th>Exerc.</th><th>Órgão.UO</th><th>Empenho</th><th>Elemento</th><th>Situação</th>
<th>Empenhado</th><th>Liquidado</th><th>Pago</th><th>Em aberto</th><th>Desde</th><th>Histórico / alertas</th></tr></thead><tbody>{''.join(linhas)}</tbody></table></div>
<p class='mut'>Valores nominais, sem atualização monetária nem juros. Data-base {fmt_data(c.data_base)}.</p>
<h2>Portais da transparência para conferência</h2><ul>{''.join(links)}</ul>
<h2>Fundamentos para a cobrança</h2><ul>{fund}</ul>
<h2>Documentos a reunir</h2><ul>{chk}</ul>
<h2>Caminhos possíveis</h2><ul>
<li>Requerimento administrativo de pagamento (e de reconhecimento de dívida, se o resto a pagar foi cancelado), com pedido de atualização monetária e observância da ordem cronológica.</li>
<li>Representação ao TCE-CE / Ministério Público de Contas por quebra da ordem cronológica ou cancelamento indevido de restos a pagar processados.</li>
<li>Ação de cobrança ou monitória (Súmula 339/STJ), com pagamento por precatório ou RPV (CF, art. 100).</li>
</ul>
<div class='aviso'>{e(AVISO_ETICO)}</div>
"""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(_pagina(cr.nome, corpo), encoding="utf-8")


def gerar_tudo(saida: Path, credores: list[Credor], municipios: list[dict], c: Criterios,
               portais: dict[str, str], max_dossies: int = 300) -> dict[str, Path]:
    saida.mkdir(parents=True, exist_ok=True)
    deb = linhas_debitos(credores)
    cred = linhas_credores(credores)
    arquivos = {}
    gravar_csv(saida / "credores.csv", cred)
    gravar_csv(saida / "debitos_por_empenho.csv", deb)
    gravar_csv(saida / "municipios.csv", municipios)
    arquivos["credores.csv"] = saida / "credores.csv"
    arquivos["debitos_por_empenho.csv"] = saida / "debitos_por_empenho.csv"
    arquivos["municipios.csv"] = saida / "municipios.csv"
    if gravar_xlsx(saida / "radar_credores.xlsx", {"Credores": cred, "Débitos por empenho": deb, "Municípios": municipios}):
        arquivos["radar_credores.xlsx"] = saida / "radar_credores.xlsx"
    dossies = {}
    usados = set()
    for cr in credores[:max_dossies]:
        nome = _slug((re.sub(r"\D", "", cr.doc) or "") + "_" + cr.nome)
        while nome in usados:
            nome += "_"
        usados.add(nome)
        rel = f"dossies/{nome}.html"
        gravar_dossie(saida / rel, cr, c, portais)
        dossies[cr.chave] = rel
    gravar_painel(saida / "painel.html", credores, municipios, c, dossies)
    arquivos["painel.html"] = saida / "painel.html"
    (saida / "criterios.json").write_text(json.dumps({
        "data_base": c.data_base.isoformat(), "meses_minimo": c.meses_minimo,
        "data_limite": c.data_limite.isoformat(), "valor_minimo": c.valor_minimo,
        "incluir_nao_processados": c.incluir_nao_processados,
        "incluir_pessoa_fisica": c.incluir_pessoa_fisica, "todos_elementos": c.todos_elementos,
    }, indent=2), encoding="utf-8")
    return arquivos
