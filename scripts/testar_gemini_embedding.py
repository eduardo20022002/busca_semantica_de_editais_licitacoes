"""Teste de fumaça do Gemini Embedding, em pequena escala, antes de qualquer
mudança no pipeline de produção (que hoje usa só Voyage, ADR-0001).

Verifica: a chave funciona, o formato de resposta é o esperado, a dimensão do
vetor, e se `similaridade_cosseno` (já usada no projeto) diferencia textos
similares de diferentes usando esse novo modelo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from editais.triagem import similaridade_cosseno  # noqa: E402

URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
MODELO = "models/gemini-embedding-001"


def carregar_dotenv(caminho: Path = Path(".env")) -> None:
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


def embeddar(chave: str, textos: list[str], input_type: str) -> list[list[float]]:
    corpo = {
        "requests": [
            {
                "model": MODELO,
                "content": {"parts": [{"text": texto}]},
                "taskType": input_type,
            }
            for texto in textos
        ]
    }
    resposta = requests.post(
        URL,
        headers={"Content-Type": "application/json", "x-goog-api-key": chave},
        json=corpo,
        timeout=60,
    )
    if resposta.status_code != 200:
        raise RuntimeError(f"HTTP {resposta.status_code}: {resposta.text[:500]}")
    dados = resposta.json()
    return [item["values"] for item in dados["embeddings"]]


def main() -> None:
    carregar_dotenv()
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY não está definida no ambiente nem em .env.")

    # Um trecho real de chunk (edital) e uma Aplicação Típica real de Produto
    # Aurora, mais um texto de controle sem relação nenhuma com saúde/TI.
    textos = [
        "1. DO OBJETO. A presente licitação tem por objeto a contratação de "
        "solução informatizada de gestão de saúde com prontuário eletrônico "
        "do paciente (PEC) para atendimento das Unidades Básicas de Saúde.",
        "Gestão de prontuário eletrônico do paciente (PEP) integrado a "
        "agenda, leitos e faturamento hospitalar.",
        "Aquisição de gêneros alimentícios perecíveis para a merenda escolar "
        "da rede municipal de ensino fundamental.",
    ]

    print("Embeddando 3 textos de teste (document)...", flush=True)
    vetores = embeddar(chave, textos, input_type="RETRIEVAL_DOCUMENT")

    print(f"OK — {len(vetores)} vetores recebidos.")
    print(f"Dimensão do vetor: {len(vetores[0])}")

    sim_relacionado = similaridade_cosseno(vetores[0], vetores[1])
    sim_nao_relacionado = similaridade_cosseno(vetores[0], vetores[2])

    print(f"\nSimilaridade (edital PEC x Aplicação Típica PEP, esperado ALTO): {sim_relacionado:.4f}")
    print(f"Similaridade (edital PEC x merenda escolar, esperado BAIXO):      {sim_nao_relacionado:.4f}")

    if sim_relacionado > sim_nao_relacionado:
        print("\n[OK] O modelo separa texto relacionado de não relacionado, como esperado.")
    else:
        print("\n[ALERTA] Similaridade não fez sentido — investigar antes de prosseguir.")


if __name__ == "__main__":
    main()
