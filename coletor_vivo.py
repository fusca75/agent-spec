#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coletor_vivo.py
Coleta continua de dados oficiais para a dashboard de repasses municipais.

Fontes (somente portais oficiais):
  1. IBGE Localidades          -> identificacao do municipio (sem chave)
  2. Siconfi / Tesouro Nacional -> RREO (execucao corrente), extrato de entregas, DCA (sem chave)
  3. Portal da Transparencia   -> convenios com liberacao na data, recursos recebidos,
                                  Bolsa Familia (requer chave: variavel PT_API_KEY)

Saida: data/repasses_live.json (carregado pela dashboard)

Uso:
  python coletor_vivo.py                 # uma coleta
  python coletor_vivo.py --loop          # coleta continuata (padrao: 15 min)
  python coletor_vivo.py --loop --intervalo 300
  python coletor_vivo.py --somente-siconfi
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUT_FILE = DATA_DIR / "repasses_live.json"

MUNICIPIO_IBGE = 3545803
MUNICIPIO_NOME_FALLBACK = "Santa Barbara d'Oeste"
MUNICIPIO_UF_FALLBACK = "SP"

IBGE_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios/{ibge}"
SICONFI_BASE = "https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/"
PT_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"

USER_AGENT = "monitor-verbas-publicas-municipais/1.0 (dashboard local de transparencia)"
SICONFI_MIN_INTERVAL = 1.1  # limite oficial de 1 requisicao por segundo

_last_siconfi_call = 0.0


def agora_iso():
    return datetime.now().isoformat(timespec="seconds")


def hoje_str():
    return date.today().isoformat()


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _ler_corpo(res):
    corpo = res.read()
    if corpo[:2] == b"\x1f\x8b":
        corpo = gzip.decompress(corpo)
    texto = corpo.decode("utf-8", errors="replace")
    return json.loads(texto)


def http_get_json(url, headers=None, timeout=60, espera_siconfi=False):
    """Retorna (dados, erro). dados=None quando ha falha; erro contem o motivo."""
    global _last_siconfi_call
    if espera_siconfi:
        decorrido = time.time() - _last_siconfi_call
        if decorrido < SICONFI_MIN_INTERVAL:
            time.sleep(SICONFI_MIN_INTERVAL - decorrido)
    cabecalhos = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        cabecalhos.update(headers)
    req = urllib.request.Request(url, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return _ler_corpo(res), None
    except urllib.error.HTTPError as exc:
        detalhe = ""
        try:
            detalhe = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        return None, f"HTTP {exc.code}: {detalhe or exc.reason}"
    except Exception as exc:  # rede, timeout, JSON invalido
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        if espera_siconfi:
            _last_siconfi_call = time.time()


def fonte(nome, url, status, aviso="", atualizado_em=None):
    return {
        "nome": nome,
        "url": url,
        "status": status,  # ok | erro | sem_chave | vazio | parcial
        "atualizado_em": atualizado_em or agora_iso(),
        "aviso": aviso,
    }


def pick(obj, *nomes, padrao=None):
    """Busca defensiva de campo em dicionario (fontes podem variar a nomenclatura)."""
    if isinstance(obj, dict):
        for nome in nomes:
            if nome in obj and obj[nome] is not None:
                return obj[nome]
    return padrao


def texto_de(valor, *chaves):
    """Extrai texto de valor que pode ser dict, lista ou string."""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, dict):
        return pick(valor, *chaves, "nome", "descricao", "codigo", padrao=str(valor)) or str(valor)
    if isinstance(valor, list):
        partes = [texto_de(v, *chaves) for v in valor]
        return ", ".join(p for p in partes if p)
    return str(valor) if valor is not None else ""


def para_float(valor):
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip().replace("R$", "").replace("%", "").replace(" ", "")
    if not s:
        return 0.0
    # formato brasileiro: 1.234,56 -> 1234.56
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def linha(area, esfera, orgao, programa, bruto, ded, liq, status, nota, fonte_nome, data=None, periodo=None):
    return {
        "area": area,
        "esfera": esfera,
        "orgao": orgao,
        "programa": programa,
        "bruto": round(bruto, 2),
        "ded": round(ded, 2),
        "liq": round(liq, 2),
        "status": status,
        "nota": nota,
        "fonte": fonte_nome,
        "data": data,
        "periodo": periodo,
    }


# --------------------------------------------------------------------------- #
# 1) IBGE
# --------------------------------------------------------------------------- #
def coletar_ibge():
    url = IBGE_URL.format(ibge=MUNICIPIO_IBGE)
    nome_fallback = MUNICIPIO_NOME_FALLBACK if MUNICIPIO_IBGE == 3545803 else f"Município IBGE {MUNICIPIO_IBGE}"
    uf_fallback = MUNICIPIO_UF_FALLBACK if MUNICIPIO_IBGE == 3545803 else ""
    dados, erro = http_get_json(url, timeout=30)
    if erro or not isinstance(dados, dict) or not dados.get("id"):
        return (
            {"ibge": MUNICIPIO_IBGE, "nome": nome_fallback, "uf": uf_fallback},
            fonte("IBGE - Localidades", url, "erro" if erro else "vazio",
                  f"Identificacao nao confirmada na API do IBGE: {erro or 'sem dados'}"),
        )
    mic = dados.get("microrregiao") or {}
    meso = mic.get("mesorregiao") or {}
    uf = (meso.get("UF") or {}).get("sigla", uf_fallback)
    mun = {
        "ibge": dados.get("id", MUNICIPIO_IBGE),
        "nome": dados.get("nome", nome_fallback),
        "uf": uf,
        "regiao": (mic.get("nome") or ""),
    }
    return mun, fonte("IBGE - Localidades", url, "ok", "", dados.get("nome") and None)


# --------------------------------------------------------------------------- #
# 2) SICONFI / Tesouro Nacional
# --------------------------------------------------------------------------- #
def _siconfi(endpoint, params):
    url = SICONFI_BASE + endpoint + "?" + urllib.parse.urlencode(params)
    dados, erro = http_get_json(url, espera_siconfi=True, timeout=90)
    return dados, erro, url


def _acha_rreo_vigente():
    """Procura o ultimo RREO disponivel do exercicio corrente (bimestral)."""
    ano_atual = date.today().year
    hoje = date.today()
    ultimo_bimestre_possivel = min(6, max(1, (hoje.month - 1) // 2))
    ultimo_erro = None
    for ano in (ano_atual, ano_atual - 1):
        inicio = ultimo_bimestre_possivel if ano == ano_atual else 6
        for periodo in range(inicio, 0, -1):
            dados, erro, url = _siconfi(
                "rreo",
                {
                    "an_exercicio": ano,
                    "nr_periodo": periodo,
                    "co_tipo_demonstrativo": "RREO",
                    "id_ente": MUNICIPIO_IBGE,
                },
            )
            if not erro and isinstance(dados, dict) and dados.get("count"):
                return dados, ano, periodo, url, None
            ultimo_erro = ultimo_erro or erro
    return None, None, None, SICONFI_BASE + "rreo", ultimo_erro or "Nenhum RREO localizado."


COLUNA_ACUM = "Até o Bimestre (c)"
COLUNA_BIMESTRE = "No Bimestre (b)"
COLUNA_PREV_ATUAL = "PREVISÃO ATUALIZADA (a)"

MAPEAMENTO_ORIGEM = {
    "TransferenciasCorrentes": ("Transferências Correntes", "Multigovernamental", "Todos os entes (consolidado)"),
    "TransferenciasCorrentesDaUniaoEDeSuasEntidades": ("Transferências Correntes", "Federal", "União - Tesouro Nacional e órgãos federais"),
    "TransferenciasCorrentesDosEstadosEDistritoFederalEDeSuasEntidades": ("Transferências Correntes", "Estadual", "Estado de SP - SEFAZ/Secretarias"),
    "TransferenciasCorrentesDeOutrasInstituicoesPublicas": ("Transferências Correntes", "Multigovernamental", "Outras instituições públicas (ex.: FUNDEB)"),
    "TransferenciasCorrentesDeInstituicoesPrivadas": ("Transferências Correntes", "Privada", "Instituições privadas e doações"),
    "TransferenciasDeCapital": ("Transferências de Capital", "Multigovernamental", "Todos os entes (consolidado)"),
    "TransferenciasDeCapitalDaUniaoEDeSuasEntidades": ("Transferências de Capital", "Federal", "União - Tesouro Nacional e órgãos federais"),
    "TransferenciasDeCapitalDosEstadosEDistritoFederalEDeSuasEntidades": ("Transferências de Capital", "Estadual", "Estado de SP - SEFAZ/Secretarias"),
}

STATUS_EM_DIA = "Em dia"
STATUS_PENDENTE = "Pendente"
STATUS_INDET = "Indeterminado"


def _status_por_previsao(previsao, realizado, acumulado_col):
    """Nao converte previsao orcamentaria agregada em cronograma de pagamento."""
    detalhe = "O RREO informa previsao e realizacao agregadas, sem vencimento individual do repasse."
    if previsao <= 0:
        detalhe += " Nao ha previsao atualizada positiva para cotejo."
    elif realizado <= 0:
        detalhe += f" A realizacao acumulada ate {acumulado_col} e zero; sem calendario nao e possivel afirmar atraso."
    else:
        detalhe += f" Previsao: {previsao:,.2f} BRL; realizacao: {realizado:,.2f} BRL."
    return STATUS_INDET, detalhe


def montar_linhas_rreo(itens, exercicio, periodo):
    por_cod = {}
    for it in itens:
        por_cod.setdefault(it.get("cod_conta"), []).append(it)

    linhas = []
    for cod, (area, esfera, orgao) in MAPEAMENTO_ORIGEM.items():
        registros = por_cod.get(cod)
        if not registros:
            continue
        acumulado = bimestre = previsao = None
        for r in registros:
            col = r.get("coluna")
            val = para_float(r.get("valor"))
            if col == COLUNA_ACUM:
                acumulado = val
            elif col == COLUNA_BIMESTRE:
                bimestre = val
            elif col == COLUNA_PREV_ATUAL:
                previsao = val
        if acumulado is None and previsao is None:
            continue
        acumulado = acumulado or 0.0
        previsao = previsao or 0.0
        status, nota = _status_por_previsao(previsao, acumulado, COLUNA_ACUM)
        nome_conta = registros[0].get("conta") or cod
        periodo_txt = f"{periodo}º bimestre de {exercicio}"
        nota = f"{nota} (Período: {periodo_txt}.)"
        if bimestre is not None:
            nota = f"Realizado no bimestre: {bimestre:,.2f} BRL. {nota}"
        linhas.append(
            linha(
                area=area,
                esfera=esfera,
                orgao=orgao,
                programa=nome_conta,
                bruto=acumulado,
                ded=0.0,
                liq=acumulado,
                status=status,
                nota=nota,
                fonte_nome="Siconfi/STN - RREO",
                data=None,
                periodo=periodo_txt,
            )
        )
    return linhas


def _status_mensal(valores):
    """Serie mensal sem calendario de vencimento nao permite avaliar pontualidade."""
    positivos = sum(1 for valor in valores if valor > 0)
    if not valores:
        return STATUS_INDET, "Fonte nao registra serie mensal; sem base para classificar regularidade."
    return STATUS_INDET, (
        f"Serie do RREO: {positivos} de {len(valores)} meses com valores registrados; "
        "a fonte nao informa o calendario previsto de cada parcela."
    )


def montar_linhas_fundeb(itens, exercicio, periodo):
    linhas = []
    alvos = {
        "DeducaoDeReceitaParaFormacaoDoFUNDEB": (
            "FUNDEB (Educação)",
            "Multigovernamental",
            "Retenção de 20% na fonte - Tesouro Nacional",
            "Dedução de Receita para Formação do FUNDEB",
            "deducao",
        ),
        "RREO3TransferenciasDoFUNDEB": (
            "FUNDEB (Educação)",
            "Multigovernamental",
            "Fundo Nacional de Desenvolvimento da Educação",
            "Transferências do FUNDEB (retorno ao município)",
            "repasse",
        ),
    }
    periodo_txt = f"{periodo}º bimestre de {exercicio}"
    for cod, (area, esfera, orgao, programa, natureza) in alvos.items():
        registros = [it for it in itens if it.get("cod_conta") == cod]
        if not registros:
            continue
        mensal = []
        total_12m = 0.0
        previsao = 0.0
        for r in registros:
            col = r.get("coluna") or ""
            val = para_float(r.get("valor"))
            if re.fullmatch(r"<MR(-\d+)?>", col):
                mensal.append(val)
            elif col.startswith("TOTAL (ÚLTIMOS 12 MESES)"):
                total_12m = val
            elif col.startswith("PREVISÃO ATUALIZADA"):
                previsao = val
        status, nota = _status_mensal(mensal)
        nota = f"{nota} (Período: {periodo_txt}.)"
        if previsao:
            nota += f" Previsão atualizada 2026: {previsao:,.2f} BRL."
        valor = total_12m or (mensal[-1] * 12 if mensal else 0.0)
        linhas.append(
            linha(
                area=area,
                esfera=esfera,
                orgao=orgao,
                programa=programa,
                bruto=valor if natureza == "repasse" else 0.0,
                ded=valor if natureza == "deducao" else 0.0,
                liq=valor if natureza == "repasse" else -valor,
                status=status,
                nota=nota,
                fonte_nome="Siconfi/STN - RREO Anexo 03",
                data=None,
                periodo=periodo_txt,
            )
        )
    return linhas


def coletar_siconfi():
    fontes, linhas, execucao = [], [], None

    dados, exercicio, periodo, url, erro = _acha_rreo_vigente()
    if dados:
        itens = dados.get("items", [])
        linhas = montar_linhas_rreo(itens, exercicio, periodo)
        linhas += montar_linhas_fundeb(itens, exercicio, periodo)
        execucao = {
            "exercicio": exercicio,
            "periodo": periodo,
            "descricao": f"{periodo}º bimestre de {exercicio}",
            "linhas": len(linhas),
        }
        fontes.append(
            fonte(
                "Siconfi/STN - RREO",
                url,
                "ok",
                f"{dados.get('count', 0)} registros do {periodo}º bimestre de {exercicio}.",
            )
        )
    else:
        fontes.append(fonte("Siconfi/STN - RREO", url, "erro", erro or "Nenhum RREO localizado."))

    # Extrato de entregas: mostra a data de atualizacao de cada relatorio no Siconfi
    dados, erro, url = _siconfi(
        "extrato_entregas", {"id_ente": MUNICIPIO_IBGE, "an_referencia": date.today().year}
    )
    entregas = []
    if not erro and isinstance(dados, dict) and dados.get("count"):
        for it in dados.get("items", [])[:60]:
            entregas.append(
                {
                    "tipo": pick(it, "entregavel", "tipo_relatorio", padrao=""),
                    "periodo": pick(it, "periodo", padrao=None),
                    "situacao": pick(it, "status_relatorio", padrao="") or "Sem status publicado",
                    "data_status": pick(it, "data_status", padrao="") or "",
                    "instituicao": pick(it, "instituicao", padrao=""),
                }
            )
        fontes.append(
            fonte("Siconfi/STN - Extrato de entregas", url, "ok",
                  f"{dados.get('count')} entregas registradas no exercicio.")
        )
    else:
        fontes.append(fonte("Siconfi/STN - Extrato de entregas", url,
                            "erro" if erro else "vazio", erro or "Sem entregas registradas."))

    # DCA: ultimo exercicio encerrado disponivel
    dca_ultimo = None
    for ano in range(date.today().year - 1, date.today().year - 4, -1):
        dados, erro, url = _siconfi("dca", {"an_exercicio": ano, "id_ente": MUNICIPIO_IBGE})
        if not erro and isinstance(dados, dict) and dados.get("count"):
            dca_ultimo = {"exercicio": ano, "registros": dados.get("count"), "url": url}
            fontes.append(
                fonte("Siconfi/STN - DCA", url, "ok",
                      f"DCA {ano} com {dados.get('count')} registros (ultimo balanco anual homologado).")
            )
            break
        time.sleep(SICONFI_MIN_INTERVAL)
    if dca_ultimo is None:
        fontes.append(fonte("Siconfi/STN - DCA", SICONFI_BASE + "dca", "vazio",
                            "Nenhum DCA de exercicios anteriores localizado."))

    return fontes, linhas, execucao, entregas, dca_ultimo


# --------------------------------------------------------------------------- #
# 3) Portal da Transparencia (chave gratuita)
# --------------------------------------------------------------------------- #
def chave_api():
    return os.environ.get("PT_API_KEY", "").strip()


def _pt_get(caminho, params):
    chave = chave_api()
    if not chave:
        return None, "sem_chave", ""
    url = PT_BASE + caminho + "?" + urllib.parse.urlencode(params)
    dados, erro = http_get_json(url, headers={"chave-api-dados": chave}, timeout=60)
    if erro:
        return None, "erro", f"{url} -> {erro}"
    return dados, "ok", url


def _nome_orgao(convenio):
    orgao = pick(convenio, "orgao", padrao="")
    nome = texto_de(orgao, "nome", "sigla", "descricao", "codigo")
    if isinstance(orgao, dict) and not nome:
        nome = str(orgao)
    return nome or "Órgão não informado na fonte"


def _status_convenio(convenio, hoje):
    """Classifica como pendente somente situacao explicitamente suspensa/cancelada."""
    vig_fim = pick(convenio, "dataFinalVigencia", padrao="") or ""
    situacao = (texto_de(pick(convenio, "situacao", padrao=""), "nome", "descricao") or "").strip()
    conclusao = pick(convenio, "dataConclusao", padrao="") or ""
    liberado = para_float(pick(convenio, "valorLiberado", padrao=0))
    total = para_float(pick(convenio, "valor", padrao=0))
    situacao_baixa = situacao.lower()

    if any(p in situacao_baixa for p in ("cancelad", "suspenso", "rescind")):
        return STATUS_PENDENTE, f"A fonte registra a situacao '{situacao}' do instrumento."
    if conclusao:
        return STATUS_INDET, f"Instrumento concluido em {conclusao}; a fonte nao informa cronograma para avaliar prazo."
    if vig_fim and vig_fim < hoje:
        if total and liberado < total - 0.01:
            return STATUS_INDET, (
                f"Vigencia encerrada em {vig_fim} com saldo nao liberado "
                f"({total - liberado:,.2f} BRL); sem cronograma nao e possivel confirmar atraso."
            )
        return STATUS_INDET, f"Vigencia encerrada em {vig_fim}; fonte nao informa cronograma para cotejar prazo."
    if liberado > 0:
        return STATUS_INDET, "Ha liberacao registrada, mas a fonte nao informa cronograma previsto para avaliar pontualidade."
    return STATUS_INDET, "Instrumento sem valor liberado informado e sem cronograma de pagamento; prazo indeterminado."


def _linha_convenio(convenio, hoje, contexto):
    liberacao = pick(convenio, "dataUltimaLiberacao", padrao="") or ""
    total = para_float(pick(convenio, "valor", padrao=0))
    liberado = para_float(pick(convenio, "valorLiberado", padrao=0))
    ultima = para_float(pick(convenio, "valorDaUltimaLiberacao", padrao=0))
    convenente = texto_de(
        pick(convenio, "municipioConvenente", "convenente", padrao=""), "nome", "municipio", "nomeMunicipio"
    )
    numero = pick(convenio, "id", padrao="") or pick(convenio, "numeroProcesso", padrao="")
    tipo = texto_de(pick(convenio, "tipoInstrumento", padrao=""), "nome", "descricao", "codigo") or "Instrumento"
    status, nota = _status_convenio(convenio, hoje)
    nota = f"{nota} Liberado no instrumento: {liberado:,.2f} BRL de {total:,.2f} BRL."
    if contexto == "hoje" and ultima:
        nota = f"Última liberação de {ultima:,.2f} BRL registrada em {liberacao}. {nota}"
    return linha(
        area="Convênios Federais",
        esfera="Federal",
        orgao=_nome_orgao(convenio),
        programa=f"{tipo} {numero}" + (f" - {convenente}" if convenente else ""),
        bruto=total,
        ded=0.0,
        liq=liberado or ultima,
        status=status,
        nota=nota,
        fonte_nome="Portal da Transparência - Convênios",
        data=liberacao or None,
        periodo=contexto,
    )


def coletar_convenios(data_inicial, data_final, contexto, limite_paginas=5):
    params = {
        "codigoIBGE": str(MUNICIPIO_IBGE),
        "dataUltimaLiberacaoInicial": data_inicial,
        "dataUltimaLiberacaoFinal": data_final,
        "pagina": 1,
    }
    linhas, url = [], ""
    for pagina in range(1, limite_paginas + 1):
        params["pagina"] = pagina
        dados, status, url = _pt_get("/convenios", params)
        if status != "ok":
            return [], status, url
        if not isinstance(dados, list) or not dados:
            break
        hoje = hoje_str()
        linhas.extend(_linha_convenio(c, hoje, contexto) for c in dados)
        if len(dados) < 100:
            break
        time.sleep(0.7)
    return linhas, "ok" if linhas else "vazio", url


def coletar_recursos_mes(mes_ano_ini, mes_ano_fim):
    params = {
        "mesAnoInicio": mes_ano_ini,
        "mesAnoFim": mes_ano_fim,
        "codigoIBGE": str(MUNICIPIO_IBGE),
        "pagina": 1,
    }
    dados, status, url = _pt_get("/despesas/recursos-recebidos", params)
    if status != "ok":
        return [], status, url
    if not isinstance(dados, list) or not dados:
        return [], "vazio", url

    agregados = {}
    for item in dados:
        orgao = texto_de(pick(item, "orgaoSuperior", "orgao", padrao=""), "nome", "sigla", "codigo") or "Órgão não informado"
        valor = para_float(pick(item, "valorLiquido", "valor", "valorDocumento", "valorPago", padrao=0))
        data = pick(item, "data", "dataDocumento", "dataPagamento", padrao="") or ""
        chave = (orgao, data[:7] if data else "")
        reg = agregados.setdefault(chave, {"orgao": orgao, "valor": 0.0, "n": 0, "data": data})
        reg["valor"] += valor
        reg["n"] += 1
        if data and data > reg.get("data", ""):
            reg["data"] = data

    linhas = []
    hoje = hoje_str()
    for (orgao, _mes), reg in sorted(agregados.items(), key=lambda x: -x[1]["valor"])[:15]:
        linhas.append(
            linha(
                area="Recursos federais recebidos",
                esfera="Federal",
                orgao=orgao,
                programa=f"Pagamentos ao município no período {mes_ano_ini}/{mes_ano_fim}",
                bruto=reg["valor"],
                ded=0.0,
                liq=reg["valor"],
                status=STATUS_INDET,
                nota=(
                    f"{reg['n']} registro(s) na fonte. A fonte informa valores creditados, sem cronograma "
                    "prévio de repasse; classificação indeterminada."
                ),
                fonte_nome="Portal da Transparência - Recursos recebidos",
                data=reg["data"][:10] if reg["data"] else None,
                periodo=f"{mes_ano_ini}/{mes_ano_fim}",
            )
        )
    return linhas, "ok", url


def coletar_bolsa_familia(mes_ano):
    params = {"mesAno": mes_ano, "codigoIbge": str(MUNICIPIO_IBGE), "pagina": 1}
    dados, status, url = _pt_get("/novo-bolsa-familia-por-municipio", params)
    if status != "ok":
        return None, status, url
    if not isinstance(dados, list) or not dados:
        return None, "vazio", url
    item = dados[0] if isinstance(dados[0], dict) else {}
    return {
        "mes_ano": mes_ano,
        "bruto": para_float(pick(item, "valorTotal", "valor", "valorPago", padrao=0)),
        "beneficiarios": pick(item, "quantidadeBeneficiarios", "beneficiarios", "quantidade", padrao=None),
        "bruto_arredondado": para_float(pick(item, "valorTotalBruto", "valorBolsaFamilia", padrao=0)),
        "raw_keys": list(item.keys())[:20],
    }, "ok", url


# --------------------------------------------------------------------------- #
# Orquestracao
# --------------------------------------------------------------------------- #
def coletar(somente_siconfi=False, municipio_ibge=None, persistir=True):
    """Coleta dados para o municipio escolhido; por padrao, mantem o ente historico."""
    global MUNICIPIO_IBGE
    municipio_anterior = MUNICIPIO_IBGE
    if municipio_ibge is not None:
        codigo = int(municipio_ibge)
        if codigo < 1000000 or codigo > 9999999:
            raise ValueError("O codigo IBGE deve conter sete digitos.")
        MUNICIPIO_IBGE = codigo
    try:
        return _coletar_atual(somente_siconfi=somente_siconfi, persistir=persistir)
    finally:
        MUNICIPIO_IBGE = municipio_anterior


def _coletar_atual(somente_siconfi=False, persistir=True):
    log("Coleta iniciada.")
    fontes, linhas_execucao, execucao, entregas, dca = coletar_siconfi()
    municipio, fonte_ibge = coletar_ibge()
    fontes.insert(0, fonte_ibge)

    repasses_hoje, contexto_mes, bolsa = [], [], None

    if not somente_siconfi:
        hoje = date.today()
        str_hoje = hoje.strftime("%d/%m/%Y")
        primeiro_mes = hoje.replace(day=1).strftime("%d/%m/%Y")

        linhas, status, url = coletar_convenios(str_hoje, str_hoje, "hoje", limite_paginas=3)
        if status == "sem_chave":
            fontes.append(fonte(
                "Portal da Transparência - Convênios (hoje)", PT_BASE + "/convenios", "sem_chave",
                "Informe a chave gratuita em PT_API_KEY (cadastro: portaldatransparencia.gov.br/api-de-dados/cadastrar-email) "
                "para habilitar as movimentações do dia."
            ))
        elif status == "erro":
            fontes.append(fonte("Portal da Transparência - Convênios (hoje)", url, "erro",
                                "Falha na consulta de movimentações do dia."))
        else:
            repasses_hoje = linhas
            fontes.append(fonte(
                "Portal da Transparência - Convênios (hoje)", url,
                "ok" if linhas else "vazio",
                f"{len(linhas)} movimentação(ões) com liberação registrada em {str_hoje}."
                if linhas else f"Nenhuma movimentação registrada na fonte em {str_hoje}.",
            ))

        linhas, status, url = coletar_convenios(primeiro_mes, str_hoje, "mes", limite_paginas=4)
        if status == "ok":
            contexto_mes = linhas
            fontes.append(fonte(
                "Portal da Transparência - Convênios (mês corrente)", url, "ok",
                f"{len(linhas)} movimentação(ões) com liberação entre {primeiro_mes} e {str_hoje}.",
            ))
        elif status == "vazio":
            fontes.append(fonte("Portal da Transparência - Convênios (mês corrente)", url, "vazio",
                                "Sem movimentações registradas no mês corrente."))
        elif status == "sem_chave":
            fontes.append(fonte("Portal da Transparência - Convênios (mês corrente)", PT_BASE + "/convenios",
                                "sem_chave", "Chave PT_API_KEY não configurada."))
        else:
            fontes.append(fonte("Portal da Transparência - Convênios (mês corrente)", url, "erro",
                                "Falha na consulta do mês corrente."))

        mes_ano = hoje.strftime("%m/%Y")
        linhas, status, url = coletar_recursos_mes(hoje.strftime("%m/%Y"), hoje.strftime("%m/%Y"))
        if status == "ok":
            contexto_mes.extend(linhas)
            fontes.append(fonte("Portal da Transparência - Recursos recebidos", url, "ok",
                                f"{len(linhas)} agrupamento(s) de pagamentos federais no mês {mes_ano}."))
        elif status == "vazio":
            fontes.append(fonte("Portal da Transparência - Recursos recebidos", url, "vazio",
                                f"Sem pagamentos registrados para o município em {mes_ano}."))
        elif status == "sem_chave":
            fontes.append(fonte("Portal da Transparência - Recursos recebidos", PT_BASE + "/despesas",
                                "sem_chave", "Chave PT_API_KEY não configurada."))
        else:
            fontes.append(fonte("Portal da Transparência - Recursos recebidos", url, "erro",
                                "Falha na consulta de recursos recebidos."))

        bolsa_status, bolsa_url = "sem_chave", PT_BASE + "/novo-bolsa-familia-por-municipio"
        if chave_api():
            mes_ano_num = hoje.strftime("%Y%m")
            bolsa, bolsa_status, bolsa_url = coletar_bolsa_familia(mes_ano_num)
            if bolsa_status == "ok" and bolsa:
                fontes.append(fonte("Portal da Transparência - Bolsa Família", bolsa_url, "ok",
                                    f"Município no período {mes_ano}."))
            elif bolsa_status == "vazio":
                fontes.append(fonte("Portal da Transparência - Bolsa Família", bolsa_url, "vazio",
                                    f"Sem registro publicado para {mes_ano}."))
            elif bolsa_status == "erro":
                fontes.append(fonte("Portal da Transparência - Bolsa Família", bolsa_url, "erro",
                                    "Falha na consulta de Bolsa Família."))
        else:
            fontes.append(fonte("Portal da Transparência - Bolsa Família", bolsa_url, "sem_chave",
                                "Chave PT_API_KEY não configurada."))

    payload = {
        "municipio": municipio,
        "gerado_em": agora_iso(),
        "hoje": hoje_str(),
        "fontes": fontes,
        "execucao": execucao,
        "linhas_execucao": linhas_execucao,
        "repasses_hoje": repasses_hoje,
        "contexto_mes": contexto_mes,
        "entregas_siconfi": entregas,
        "dca_ultimo": dca,
        "bolsa_familia": bolsa,
        "snapshot_2024": False,
    }
    if persistir:
        gravar(payload)
    ok = sum(1 for f in fontes if f["status"] == "ok")
    log(f"Coleta concluida: {len(fontes)} fontes ({ok} ok), "
        f"{len(repasses_hoje)} movimentações hoje, {len(linhas_execucao)} linhas de execução.")
    return payload


def gravar(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT_FILE)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Coleta continuata de dados oficiais para a dashboard.")
    parser.add_argument("--loop", action="store_true", help="coleta continuata ate interromper")
    parser.add_argument("--intervalo", type=int, default=900, help="segundos entre coletas (padrao: 900 = 15 min)")
    parser.add_argument("--somente-siconfi", action="store_true", help="ignora o Portal da Transparencia")
    parser.add_argument("--municipio", type=int, default=MUNICIPIO_IBGE, help="codigo IBGE de sete digitos")
    args = parser.parse_args()

    if not args.loop:
        coletar(somente_siconfi=args.somente_siconfi, municipio_ibge=args.municipio)
        return

    log(f"Modo continuo: coleta a cada {args.intervalo}s. Ctrl+C para encerrar.")
    while True:
        try:
            coletar(somente_siconfi=args.somente_siconfi, municipio_ibge=args.municipio)
        except Exception as exc:  # falha nao pode derrubar o loop
            log(f"ERRO na coleta: {type(exc).__name__}: {exc}")
        try:
            time.sleep(max(30, args.intervalo))
        except KeyboardInterrupt:
            log("Loop encerrado.")
            break


if __name__ == "__main__":
    main()
