"""Monta e envia o top-N (por padrão, os selecionados_para_revisao — top-20 —
de dados/analise_profunda_{data}.json) para o endpoint editais-api do
backend externo (API REST).

Por padrão só IMPRIME o payload (--enviar de fato faz o POST) — mesmo padrão
de segurança usado desde o primeiro envio manual desta base.

justificativa_ia e ia_aderente vêm de dados/justificativas_{data}.json (mapa
numeroControlePNCP -> {"justificativa_ia": texto, "ia_aderente": true|false}),
produzido por uma leitura real dos documentos (humana ou de um agente) — nunca
gerado aqui. Editais sem entrada lá recebem um aviso explícito em
justificativa_ia e omitem ia_aderente (vira "não classificado" no Painel de Analistas, em
vez de uma avaliação inventada).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from editais.documentos import listar_arquivos, selecionar_documentos_principais
from editais.transporte_http import listar_arquivos_via_http
from editais.transporte_voyage import _carregar_dotenv

ENDPOINT = os.environ.get("PAINEL_API_URL", "https://api.exemplo.com/functions/v1/editais-api")
DADOS = Path("dados")
LOTE_MAXIMO = 200  # teto documentado da API — hoje sempre bem abaixo (top-20)

JUSTIFICATIVA_AUSENTE = (
    "Score calculado por similaridade vetorial contra o Perfil Aurora; sem "
    "leitura do objeto real disponível ainda. Recomenda-se revisão humana "
    "antes de decisão — runs anteriores mostraram ~70-80% de falso positivo "
    "no top do Score sem essa leitura."
)


def indexar_editais(data: str) -> dict[str, dict[str, Any]]:
    caminho = DADOS / f"editais_{data}.json"
    indice: dict[str, dict[str, Any]] = {}
    for edital in json.loads(caminho.read_text(encoding="utf-8")):
        indice[edital["numeroControlePNCP"]] = edital
    return indice


def carregar_top(data: str, top: int, pular: int = 0) -> list[dict[str, Any]]:
    # Ranqueia todos os analisados por Score, em vez de filtrar por
    # selecionado_para_revisao: para pular > 0 o recorte cai fora da marcação
    # (que cobre só o topo). Com pular=0 o resultado é idêntico ao da marcação,
    # já que ela é exatamente o top-N por Score.
    caminho = DADOS / f"analise_profunda_{data}.json"
    analisados = json.loads(caminho.read_text(encoding="utf-8"))
    analisados.sort(key=lambda e: e["score_aderencia"], reverse=True)
    return analisados[pular : pular + top]


def carregar_justificativas(data: str) -> dict[str, dict[str, Any]]:
    caminho = DADOS / f"justificativas_{data}.json"
    if not caminho.exists():
        return {}
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    # Aceita o formato legado (numero -> texto simples), sem ia_aderente.
    return {
        numero: valor if isinstance(valor, dict) else {"justificativa_ia": valor}
        for numero, valor in bruto.items()
    }


def link_pncp(cnpj: str, ano: int, sequencial: int) -> str:
    return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"


def buscar_documentos(edital: dict[str, Any]) -> list[dict[str, str]]:
    resultado = listar_arquivos(
        edital["orgaoEntidade"]["cnpj"],
        edital["anoCompra"],
        edital["sequencialCompra"],
        listar_arquivos_via_http,
        dormir=time.sleep,
    )
    if resultado.erro is not None:
        return []
    principais = selecionar_documentos_principais(resultado.arquivos)
    return [
        {"id": str(a.sequencial_documento), "nome": a.tipo_documento_nome, "tipo": "PDF", "url": a.url}
        for a in principais
    ]


def normalizar_data_iso(valor: str | None) -> str | None:
    if valor is None:
        return None
    if "T" in valor and not valor.endswith("Z") and "+" not in valor[10:]:
        return valor + "Z"
    return valor


def montar_editais(data: str, top: int, pular: int = 0) -> list[dict[str, Any]]:
    idx = indexar_editais(data)
    justificativas = carregar_justificativas(data)
    selecionados = carregar_top(data, top, pular)

    editais: list[dict[str, Any]] = []
    for item in selecionados:
        numero = item["numeroControlePNCP"]
        e = idx.get(numero)
        if e is None:
            print(f"  [aviso] {numero}: sem metadados em editais_{data}.json, pulado")
            continue
        cnpj = e["orgaoEntidade"]["cnpj"]
        veredito = justificativas.get(numero, {})
        registro = {
            "numero_controle_pncp": numero,
            "numero_compra": f"{e['sequencialCompra']}/{e['anoCompra']}",
            "orgao": e["orgaoEntidade"]["razaoSocial"],
            "unidade": e["unidadeOrgao"]["nomeUnidade"],
            "uf": e["unidadeOrgao"]["ufSigla"],
            "municipio": e["unidadeOrgao"]["municipioNome"],
            "modalidade": e["modalidadeNome"],
            "objeto": e["objetoCompra"],
            "valor_estimado": e.get("valorTotalEstimado"),
            "data_publicacao": normalizar_data_iso(e.get("dataPublicacaoPncp")),
            "data_abertura_propostas": e.get("dataAberturaProposta"),
            "data_encerramento_propostas": e.get("dataEncerramentoProposta"),
            "link_pncp": link_pncp(cnpj, e["anoCompra"], e["sequencialCompra"]),
            "score": round(item["score_aderencia"] * 100),
            "justificativa_ia": veredito.get("justificativa_ia", JUSTIFICATIVA_AUSENTE),
            "documentos": buscar_documentos(e),
        }
        # Só inclui ia_aderente quando temos uma leitura real — omitir (em vez
        # de enviar null) evita sobrescrever uma correção de analista em
        # reenvios futuros deste mesmo edital sem avaliação nova.
        if "ia_aderente" in veredito:
            registro["ia_aderente"] = veredito["ia_aderente"]
        editais.append(registro)
    return editais


def montar_payload(data: str, top: int, pular: int = 0) -> dict[str, Any]:
    total_coletado = len(json.loads((DADOS / f"editais_{data}.json").read_text(encoding="utf-8")))
    dia, mes, ano = data.split("-")[::-1]
    return {
        "coleta": {"periodo": f"{dia}/{mes}/{ano}", "total_coletado": total_coletado},
        "editais": montar_editais(data, top, pular),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Envia o top-N da Análise profunda ao Painel de Analistas.")
    parser.add_argument("--data", required=True, help="Data de referência (AAAA-MM-DD).")
    parser.add_argument("--top", type=int, default=20, help="Quantos editais enviar (padrão: 20).")
    parser.add_argument(
        "--pular",
        type=int,
        default=0,
        help="Pula os N primeiros do ranking (ex.: --pular 20 --top 20 envia do 21º ao 40º).",
    )
    parser.add_argument("--enviar", action="store_true", help="faz o POST de fato (padrão: dry-run).")
    args = parser.parse_args()

    if args.top > LOTE_MAXIMO:
        raise SystemExit(f"--top {args.top} excede o lote máximo de {LOTE_MAXIMO} por requisição.")

    payload = montar_payload(args.data, args.top, args.pular)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n{len(payload['editais'])} editais no payload.", flush=True)

    if not args.enviar:
        print("\n[modo dry-run — use --enviar para de fato enviar]", flush=True)
        return

    _carregar_dotenv()
    chave = os.environ["EDITAIS_API_KEY"]
    r = requests.post(
        ENDPOINT,
        headers={"x-api-key": chave, "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    print(f"\nHTTP {r.status_code}")
    print(r.text[:2000])
    r.raise_for_status()


if __name__ == "__main__":
    main()
