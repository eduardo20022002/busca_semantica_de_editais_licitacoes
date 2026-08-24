"""Monta e envia o top-10 (do run parcial de 100/300 editais de 04/08) para
o endpoint editais-api do backend externo (API REST).

Por padrão só IMPRIME o payload (--enviar de fato faz o POST) — a leitura dos
objetos reais mostrou que 8 dos 10 são falsos positivos do Score vetorial, e
a justificativa_ia de cada um reflete essa leitura honesta, não o score bruto.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from editais.transporte_voyage import _carregar_dotenv
import requests

ENDPOINT = os.environ.get("PAINEL_API_URL", "https://api.exemplo.com/functions/v1/editais-api")

# Veredito da leitura humana dos documentos reais (mensagem anterior desta
# conversa) — a justificativa_ia registra esse veredito, não só o score.
JUSTIFICATIVAS = {
    "03929049000111-1-000025/2026": (
        "Score alto por vocabulário compartilhado (\"orientação médica por telefone\", "
        "\"atendimento\"), mas o objeto real é atendimento pré-hospitalar físico "
        "(ambulância UTI móvel, médicos in loco) — serviço assistencial direto, não "
        "telessaúde nem software. Provável falso positivo."
    ),
    "82892373000189-1-000028/2026": (
        "Terceirização de corpo clínico (médico clínico, pediatra, ginecologista) para "
        "ESF/UBS — contratação de mão de obra médica presencial, sem componente de TI. "
        "Provável falso positivo."
    ),
    "08079915000146-1-000043/2026": (
        "Objeto real confirma aderência: consultoria e monitoramento de dados da Atenção "
        "Primária com implantação de software de PEC integrado ao Ministério da Saúde e "
        "hospedagem em nuvem do sistema. Bom encaixe com Software de Gestão em Saúde e "
        "Cloud para Saúde."
    ),
    "13718176000125-1-000019/2026": (
        "Objeto é gestão/operacionalização terceirizada de serviços assistenciais com "
        "disponibilização de profissionais próprios, complementar ao SUS — prestação de "
        "serviço de saúde com mão de obra, não solução de TI. Provável falso positivo."
    ),
    "27080605000609-1-000042/2026": (
        "Contratação de médicos anestesiologistas para hospital estadual — mão de obra "
        "médica especializada presencial, sem componente de TI ou telessaúde. Provável "
        "falso positivo."
    ),
    "50453703000143-1-000052/2026": (
        "Contratação de cirurgiões vasculares — mão de obra médica especializada "
        "presencial. Provável falso positivo, mesmo padrão de outros achados desta base."
    ),
    "50453703000143-1-000051/2026": (
        "Contratação de urologistas — mão de obra médica especializada presencial. "
        "Provável falso positivo, mesmo padrão do edital 50453703000143-1-000052/2026 "
        "do mesmo órgão."
    ),
    "92963560000160-1-001335/2025": (
        "Objeto real confirma aderência: contratação de consultas médicas explicitamente "
        "na modalidade de telemedicina (Neuropediatria), atendimento remoto por "
        "plataforma. É o encaixe mais direto com Telessaúde deste lote."
    ),
    "08996378000107-1-000089/2026": (
        "Objeto é consultoria e capacitação — oficinas formativas de qualificação da "
        "gestão na Atenção Básica. É treinamento humano (workshops), não um sistema de "
        "software. Provável falso positivo apesar do produto apontado ser \"gestão em "
        "saúde\"."
    ),
    "60448040000122-1-000511/2026": (
        "Objeto é aquisição de insumo físico (cabos e lâminas de laringoscópio) — "
        "material hospitalar, não solução de TI. Provável falso positivo, mesmo padrão "
        "de \"hardware/insumo\" já visto em runs anteriores."
    ),
}

SCORES = {
    "03929049000111-1-000025/2026": 0.8016,
    "82892373000189-1-000028/2026": 0.7760,
    "08079915000146-1-000043/2026": 0.7504,
    "13718176000125-1-000019/2026": 0.7498,
    "27080605000609-1-000042/2026": 0.7418,
    "50453703000143-1-000052/2026": 0.7316,
    "50453703000143-1-000051/2026": 0.7188,
    "92963560000160-1-001335/2025": 0.7134,
    "08996378000107-1-000089/2026": 0.7068,
    "60448040000122-1-000511/2026": 0.7033,
}

DADOS = Path("dados")


def indexar_editais() -> dict[str, dict]:
    indice: dict[str, dict] = {}
    for caminho in DADOS.glob("editais_*.json"):
        for edital in json.loads(caminho.read_text(encoding="utf-8")):
            indice[edital["numeroControlePNCP"]] = edital
    return indice


def link_pncp(cnpj: str, ano: int, sequencial: int) -> str:
    return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"


def montar_documentos(numero: str) -> list[dict]:
    urls = json.loads(Path("dados/urls_top10_documentos.json").read_text(encoding="utf-8"))
    return [
        {
            "id": str(a["sequencial"]),
            "nome": a["tipo"],
            "tipo": "PDF",
            "url": a["url"],
        }
        for a in urls.get(numero, [])
    ]


def montar_payload() -> dict:
    idx = indexar_editais()
    editais = []
    for numero, score in SCORES.items():
        e = idx[numero]
        cnpj = e["orgaoEntidade"]["cnpj"]
        editais.append(
            {
                "numero_controle_pncp": numero,
                "numero_compra": f"{e['sequencialCompra']}/{e['anoCompra']}",
                "orgao": e["orgaoEntidade"]["razaoSocial"],
                "unidade": e["unidadeOrgao"]["nomeUnidade"],
                "uf": e["unidadeOrgao"]["ufSigla"],
                "municipio": e["unidadeOrgao"]["municipioNome"],
                "modalidade": e["modalidadeNome"],
                "objeto": e["objetoCompra"],
                "valor_estimado": e.get("valorTotalEstimado"),
                "data_publicacao": e["dataPublicacaoPncp"] + "Z"
                if "T" in e["dataPublicacaoPncp"] and not e["dataPublicacaoPncp"].endswith("Z")
                else e["dataPublicacaoPncp"],
                "data_abertura_propostas": e.get("dataAberturaProposta"),
                "data_encerramento_propostas": e.get("dataEncerramentoProposta"),
                "link_pncp": link_pncp(cnpj, e["anoCompra"], e["sequencialCompra"]),
                "score": round(score * 100),
                "justificativa_ia": JUSTIFICATIVAS[numero],
                "documentos": montar_documentos(numero),
            }
        )
    return {
        "coleta": {"periodo": "04/08/2026", "total_coletado": 100},
        "editais": editais,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enviar", action="store_true", help="faz o POST de fato")
    args = parser.parse_args()

    payload = montar_payload()
    print(json.dumps(payload, ensure_ascii=False, indent=2))

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


if __name__ == "__main__":
    main()
