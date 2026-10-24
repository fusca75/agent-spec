#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor local da dashboard e endpoint de consulta atualizada por municipio."""

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import coletor_vivo


BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "data" / "municipios"
PORTA_PADRAO = 8000
COLETA_LOCK = threading.Lock()


def _linhas(payload, chave):
    valor = payload.get(chave, [])
    return valor if isinstance(valor, list) else []


def _chave_linha(linha):
    return tuple(str(linha.get(campo, "")) for campo in ("fonte", "programa", "data", "orgao", "bruto", "liq"))


def _mesclar_registros(atuais, anteriores, consulta_anterior):
    resultado = list(atuais)
    chaves = {_chave_linha(linha) for linha in resultado}
    adicionados = []
    for original in anteriores:
        linha = dict(original)
        chave = _chave_linha(linha)
        if chave in chaves:
            continue
        nota = linha.get("nota", "")
        if "consulta anterior" not in nota.lower():
            linha["nota"] = f"Registro recuperado da consulta anterior ({consulta_anterior}). {nota}".strip()
        resultado.append(linha)
        adicionados.append(linha)
        chaves.add(chave)
    return resultado, adicionados


def _aplicar_cache(payload, cache):
    if not cache:
        return payload

    reutilizados = []
    if not _linhas(payload, "linhas_execucao") and _linhas(cache, "linhas_execucao"):
        payload["linhas_execucao"], copiados = _mesclar_registros(
            [], cache["linhas_execucao"], cache.get("gerado_em", "consulta anterior")
        )
        payload["execucao"] = cache.get("execucao")
        reutilizados.extend(copiados)

    cache_mes = _linhas(cache, "contexto_mes")
    cache_dia = _linhas(cache, "repasses_hoje")
    if cache.get("hoje") != payload.get("hoje"):
        for linha in cache_dia:
            linha = dict(linha)
            linha["periodo"] = linha.get("data") or cache.get("hoje") or "data não informada"
            cache_mes.append(linha)
    elif not _linhas(payload, "repasses_hoje") and cache_dia:
        payload["repasses_hoje"], copiados = _mesclar_registros(
            [], cache_dia, cache.get("gerado_em", "consulta anterior")
        )
        reutilizados.extend(copiados)

    payload["contexto_mes"], copiados = _mesclar_registros(
        _linhas(payload, "contexto_mes"), cache_mes, cache.get("gerado_em", "consulta anterior")
    )
    reutilizados.extend(copiados)

    if reutilizados:
        payload["cache_data_reused"] = True
        payload["cache_data_em"] = cache.get("gerado_em")
        payload.setdefault("fontes", []).append({
            "nome": "Base local de consultas anteriores",
            "url": "",
            "status": "cache",
            "atualizado_em": cache.get("gerado_em", ""),
            "aviso": f"{len(reutilizados)} registro(s) anterior(es) reaproveitado(s); confira a data de referência em cada linha.",
        })
    return payload


def _salvar_cache(codigo_ibge, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino = CACHE_DIR / f"{codigo_ibge}.json"
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(destino)


def _normalizar_status_cache(payload):
    """Remove conclusoes de prazo antigas que nao eram sustentadas pela fonte."""
    if not isinstance(payload, dict):
        return payload
    for chave in ("repasses_hoje", "contexto_mes", "linhas_execucao"):
        linhas = payload.get(chave)
        if not isinstance(linhas, list):
            continue
        for linha in linhas:
            fonte = str(linha.get("fonte", "")).lower()
            status = str(linha.get("status", "")).lower()
            nota = str(linha.get("nota", ""))
            mudou = False
            if "siconfi" in fonte and "rreo" in fonte and status != "indeterminado":
                mudou = True
            elif "portal da transpar" in fonte and "conv" in fonte:
                explicitamente_cancelado = any(
                    termo in nota.lower() for termo in ("cancelad", "suspens", "rescind")
                )
                if status in ("em dia", "conforme") or (status == "pendente" and not explicitamente_cancelado):
                    mudou = True
            if mudou:
                linha["status"] = "Indeterminado"
                linha["nota"] = (
                    f"{nota} Status ajustado na leitura do cache: a fonte nao permite comprovar "
                    "pontualidade sem cronograma previsto."
                ).strip()
    return payload


def _ler_cache(codigo_ibge):
    caminho = CACHE_DIR / f"{codigo_ibge}.json"
    try:
        return _normalizar_status_cache(json.loads(caminho.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        if codigo_ibge == 3545803:
            legado = BASE_DIR / "data" / "repasses_live.json"
            try:
                return _normalizar_status_cache(json.loads(legado.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        return None


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/cache":
            try:
                params = parse_qs(parsed.query)
                codigo_ibge = int(params.get("municipio", [""])[0])
                if codigo_ibge < 1000000 or codigo_ibge > 9999999:
                    raise ValueError("Codigo IBGE invalido.")
            except (ValueError, TypeError):
                self._responder(400, {"erro": "Informe um codigo IBGE valido de sete digitos."})
                return
            payload = _ler_cache(codigo_ibge)
            if payload is None:
                self._responder(404, {"erro": "Ainda nao ha consulta salva para este municipio."})
                return
            self._responder(200, payload)
            return
        if parsed.path == "/":
            self.path = "/dashboard_repasses.html"
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/atualizar":
            self.send_error(404, "Endpoint nao encontrado")
            return

        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if tamanho < 1 or tamanho > 1024:
                raise ValueError("Requisicao invalida.")
            corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            codigo_ibge = int(corpo.get("municipio"))
            if codigo_ibge < 1000000 or codigo_ibge > 9999999:
                raise ValueError("Codigo IBGE invalido.")
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as erro:
            self._responder(400, {"erro": str(erro)})
            return

        try:
            # O coletor tem estado global para respeitar o intervalo oficial do Siconfi.
            # A trava tambem impede duas consultas simultaneas de sobrescreverem o ente.
            with COLETA_LOCK:
                payload = coletor_vivo.coletar(municipio_ibge=codigo_ibge, persistir=False)
                payload = _aplicar_cache(payload, _ler_cache(codigo_ibge))
                _salvar_cache(codigo_ibge, payload)
            self._responder(200, payload)
        except Exception as erro:
            coletor_vivo.log(f"Falha na consulta do municipio {codigo_ibge}: {erro}")
            self._responder(502, {"erro": "Nao foi possivel atualizar os dados nas fontes oficiais."})

    def _responder(self, status, payload):
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)


def main():
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA_PADRAO), DashboardHandler)
    print(f"Dashboard local em http://127.0.0.1:{PORTA_PADRAO}")
    print("Mantenha esta janela aberta enquanto consulta dados oficiais.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
