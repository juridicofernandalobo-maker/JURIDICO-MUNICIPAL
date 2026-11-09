"""Cliente da API de Dados Abertos do SIM (TCE-CE) com cache local em SQLite.

Documentação oficial: https://api-dados-abertos.tce.ce.gov.br/sim/
(OpenAPI em https://api-dados-abertos.tce.ce.gov.br/sim/openapi_prod.yaml)

Pontos do SIM que o sistema usa:

* ``exercicio_orcamento`` vem no formato AAAA00 (ex.: 202400);
* ``data_referencia_doc`` é o mês de envio no formato AAAAMM e é obrigatório
  nas tabelas de despesa;
* liquidações e pagamentos de restos a pagar ficam no exercício do empenho,
  com ``data_referencia_doc`` dos anos seguintes;
* máximo de 1000 registros por requisição (paginação com ``$start_index``).
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE_URL = "https://api-dados-abertos.tce.ce.gov.br/sim/"
PAGINA = 1000
USER_AGENT = "juridico-municipal/0.1 (dados abertos SIM)"


class ErroAPI(RuntimeError):
    pass


def ref_fechada(ref: int, hoje: date | None = None, carencia_meses: int = 3) -> bool:
    """Um mês de referência é tratado como fechado (não muda mais) depois da carência.

    Os municípios enviam o SIM com atraso e ainda retificam os meses recentes,
    por isso os últimos ``carencia_meses`` são sempre consultados de novo.
    """
    hoje = hoje or date.today()
    ano, mes = divmod(ref, 100)
    atual = hoje.year * 12 + hoje.month
    return (ano * 12 + mes) <= atual - carencia_meses


class Cache:
    def __init__(self, caminho: Path):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(caminho), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS resposta ("
                " chave TEXT PRIMARY KEY, obtido_em REAL, fechado INTEGER, dados BLOB)"
            )
            self._db.commit()

    def ler(self, chave: str, validade_s: float | None):
        with self._lock:
            row = self._db.execute(
                "SELECT obtido_em, fechado, dados FROM resposta WHERE chave=?", (chave,)
            ).fetchone()
        if not row:
            return None
        obtido_em, fechado, dados = row
        if not fechado and validade_s is not None and time.time() - obtido_em > validade_s:
            return None
        return json.loads(gzip.decompress(dados))

    def gravar(self, chave: str, fechado: bool, registros: list) -> None:
        blob = gzip.compress(json.dumps(registros, ensure_ascii=False).encode())
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO resposta VALUES (?,?,?,?)",
                (chave, time.time(), int(fechado), blob),
            )
            self._db.commit()


class ClienteSIM:
    def __init__(
        self,
        cache_dir: Path | str = ".cache",
        base_url: str = BASE_URL,
        timeout: float = 180,
        tentativas: int = 5,
        validade_aberto_s: float = 24 * 3600,
        usar_cache: bool = True,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.tentativas = tentativas
        self.validade_aberto_s = validade_aberto_s
        self.cache = Cache(Path(cache_dir) / "sim.sqlite") if usar_cache else None
        self.requisicoes = 0

    # ------------------------------------------------------------------ HTTP
    def _get_json(self, metodo: str, params: dict) -> dict:
        url = self.base_url + metodo + "?" + urllib.parse.urlencode(params)
        espera = 2.0
        ultimo: Exception | None = None
        for _ in range(self.tentativas):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    self.requisicoes += 1
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                corpo = e.read().decode("utf-8", "replace")[:300]
                if 400 <= e.code < 500 and e.code != 429:
                    raise ErroAPI(f"{metodo} {params}: HTTP {e.code} {corpo}") from e
                ultimo = e
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                ultimo = e
            time.sleep(espera)
            espera *= 2
        raise ErroAPI(f"{metodo} {params}: falhou após {self.tentativas} tentativas ({ultimo})")

    def consultar(self, metodo: str, **params) -> list[dict]:
        """Retorna todos os registros (todas as páginas) da consulta."""
        registros: list[dict] = []
        inicio = 0
        while True:
            p = dict(params)
            p["$count"] = PAGINA
            p["$start_index"] = inicio
            dados = self._get_json(metodo, p)
            if "__errors__" in dados:
                raise ErroAPI(f"{metodo} {params}: {dados['__errors__']}")
            pagina = dados.get("elements", [])
            registros.extend(pagina)
            if len(pagina) < PAGINA:
                return registros
            inicio += PAGINA

    # ------------------------------------------------------------- com cache
    def mensal(self, metodo: str, municipio: str, exercicio: int, ref: int) -> list[dict]:
        """Consulta uma tabela de despesa para (município, exercício, mês de referência)."""
        chave = f"{metodo}|{municipio}|{exercicio}|{ref}"
        if self.cache:
            em_cache = self.cache.ler(chave, self.validade_aberto_s)
            if em_cache is not None:
                return em_cache
        regs = self.consultar(
            metodo,
            codigo_municipio=municipio,
            exercicio_orcamento=exercicio * 100,
            data_referencia_doc=ref,
        )
        if self.cache:
            self.cache.gravar(chave, ref_fechada(ref), regs)
        return regs

    def municipios(self) -> list[dict]:
        chave = "municipios"
        if self.cache:
            em_cache = self.cache.ler(chave, 30 * 24 * 3600)
            if em_cache is not None:
                return em_cache
        regs = [
            m for m in self.consultar("municipios") if m.get("codigo_municipio_ibge")
        ]
        if self.cache:
            self.cache.gravar(chave, False, regs)
        return regs
