#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor local da dashboard e endpoint de consulta atualizada por municipio."""

import json
import os
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import coletor_vivo


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", str(BASE_DIR / "data")))
CACHE_DIR = DATA_DIR / "municipios"
HOST_PADRAO = "127.0.0.1"
PORTA_PADRAO = 8000
CACHE_TTL_SEGUNDOS = 900
INTERVALO_POST_CLIENTE = 3
COLETA_LOCK = threading.Lock()
CLIENT_LOCK = threading.Lock()
ULTIMA_CONSULTA_CLIENTE = {}


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


def _cache_recente(payload):
    try:
        gerado_em = datetime.fromisoformat(payload.get("gerado_em", ""))
        idade = (datetime.now() - gerado_em).total_seconds()
        return 0 <= idade < CACHE_TTL_SEGUNDOS
    except (TypeError, ValueError):
        return False


def _cliente_em_intervalo(ip):
    agora = time.monotonic()
    with CLIENT_LOCK:
        anterior = ULTIMA_CONSULTA_CLIENTE.get(ip, 0)
        if agora - anterior < INTERVALO_POST_CLIENTE:
            return True
        ULTIMA_CONSULTA_CLIENTE[ip] = agora
        if len(ULTIMA_CONSULTA_CLIENTE) > 5000:
            expirados = [chave for chave, instante in ULTIMA_CONSULTA_CLIENTE.items() if agora - instante > 60]
            for chave in expirados:
                ULTIMA_CONSULTA_CLIENTE.pop(chave, None)
        return False


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._responder(200, {"status": "ok"})
            return
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
        if parsed.path in ("/", "/dashboard_repasses.html"):
            conteudo = (BASE_DIR / "dashboard_repasses.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(conteudo)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(conteudo)
            return
        self.send_error(404, "Endpoint nao encontrado")

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/dashboard_repasses.html", "/healthz"):
            self.send_error(404, "Endpoint nao encontrado")
            return
        if parsed.path == "/healthz":
            conteudo = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(conteudo)))
            self.end_headers()
            return
        conteudo = (BASE_DIR / "dashboard_repasses.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(conteudo)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()

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
            forcar = corpo.get("forcar") is True
            if codigo_ibge < 1000000 or codigo_ibge > 9999999:
                raise ValueError("Codigo IBGE invalido.")
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as erro:
            self._responder(400, {"erro": str(erro)})
            return

        client_ip = self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        if _cliente_em_intervalo(client_ip or self.client_address[0]):
            self._responder(429, {"erro": "Aguarde alguns segundos antes de iniciar outra consulta."})
            return

        try:
            # O coletor tem estado global para respeitar o intervalo oficial do Siconfi.
            # A trava tambem impede duas consultas simultaneas de sobrescreverem o ente.
            with COLETA_LOCK:
                cache = _ler_cache(codigo_ibge)
                if cache and _cache_recente(cache) and not forcar:
                    payload = dict(cache)
                    payload["consulta_cache"] = True
                else:
                    payload = coletor_vivo.coletar(municipio_ibge=codigo_ibge, persistir=False)
                    payload = _aplicar_cache(payload, cache)
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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        self.wfile.write(corpo)


def main():
    host = os.environ.get("HOST", HOST_PADRAO)
    porta = int(os.environ.get("PORT", str(PORTA_PADRAO)))
    servidor = ThreadingHTTPServer((host, porta), DashboardHandler)
    print(f"Dashboard em http://{host}:{porta}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
