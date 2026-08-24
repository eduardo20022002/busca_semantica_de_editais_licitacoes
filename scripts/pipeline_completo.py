"""Pipeline completo: Coleta -> Triagem -> Análise profunda -> Routine (LLM) -> Envio.

Uso: python scripts/pipeline_completo.py --data 2026-08-12 [--enviar]

Etapas 0-2 reusam os CLIs já existentes do projeto (subprocess, mesmo
comportamento testado em produção). A Etapa 3 (Routine) é nova: troca a
leitura manual dos documentos por uma chamada à API da Anthropic por edital,
com saída estruturada. A Etapa 4 reusa scripts/enviar_painel.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anthropic

# ajuste os imports abaixo se os caminhos dos módulos mudarem
from editais.documentos import listar_arquivos, selecionar_documentos_principais
from editais.extracao import extrair_textos_de_arquivo
from editais.transporte_http import listar_arquivos_via_http, baixar_arquivo_via_http
from editais.transporte_voyage import _carregar_dotenv

DADOS = Path("dados")
TOP_N_REVISAO = 20

# custo-benefício: julgamento com nuance (telemedicina x contratação de
# médicos), não precisa do tier mais caro. Troque para claude-haiku-4-5 se
# quiser reduzir custo e aceitar mais risco de erro nos casos ambíguos.
MODELO_ROUTINE = "claude-sonnet-5"
MAX_TOKENS_ROUTINE = 1024
CARACTERES_MAX_POR_DOCUMENTO = 6000  # ajuste conforme o tamanho real dos seus editais

ESCOPO_PRODUTO = """
IA para Saúde, Software de Gestão em Saúde, Telessaúde, Cloud para Saúde,
Interoperabilidade em Saúde, Cibersegurança em Saúde.
""".strip()

# PLACEHOLDER — substitua pelos padrões reais já observados no seu histórico
# (ex.: dados/justificativas_*.json de rodadas anteriores)
PADROES_FALSO_POSITIVO = """
- Terceirização de mão de obra médica/assistencial presencial, sem componente de TI
- Hardware ou insumo médico-hospitalar
- Serviço de saúde direto (exames, home care, atenção domiciliar) sem TI
- Sistema/infra de TI genérica sem recorte de saúde
""".strip()

VEREDITO_SCHEMA = {
    "type": "object",
    "properties": {
        "ia_aderente": {
            "type": "boolean",
            "description": "true se o edital é genuinamente aderente ao Escopo Aurora; false se for falso positivo do Score.",
        },
        "justificativa_ia": {
            "type": "string",
            "description": "1-2 frases citando o objeto real do edital, no mesmo padrão de estilo de runs anteriores.",
        },
    },
    "required": ["ia_aderente", "justificativa_ia"],
    "additionalProperties": False,
}


def rodar_etapa0_coleta(data: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "editais.cli_coleta", "--data", data], check=True
    )


def rodar_etapa1_triagem(data: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "editais.cli_triagem", "--data", data], check=True
    )


def rodar_etapa2_analise_profunda(data: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "editais.cli_analise_profunda", "--data", data],
        check=True,
    )


def _carregar_top_selecionados(data: str, top: int) -> list[dict[str, Any]]:
    caminho = DADOS / f"analise_profunda_{data}.json"
    analisados = json.loads(caminho.read_text(encoding="utf-8"))
    selecionados = [e for e in analisados if e.get("selecionado_para_revisao")]
    selecionados.sort(key=lambda e: e["score_aderencia"], reverse=True)
    return selecionados[:top]


def _indexar_editais(data: str) -> dict[str, dict[str, Any]]:
    caminho = DADOS / f"editais_{data}.json"
    return {e["numeroControlePNCP"]: e for e in json.loads(caminho.read_text(encoding="utf-8"))}


def _texto_documento_principal(edital: dict[str, Any]) -> str:
    """Baixa e extrai o texto do Edital/TR principal. Retorna string vazia em falha."""
    resultado = listar_arquivos(
        edital["orgaoEntidade"]["cnpj"],
        edital["anoCompra"],
        edital["sequencialCompra"],
        listar_arquivos_via_http,
        dormir=time.sleep,
    )
    if resultado.erro is not None:
        return ""

    principais = selecionar_documentos_principais(resultado.arquivos)
    textos: list[str] = []
    for arquivo in principais:
        baixado = baixar_arquivo_via_http(arquivo.url)
        if baixado.status_code != 200 or baixado.conteudo is None:
            continue
        nome = baixado.nome_arquivo or arquivo.titulo
        extraidos = extrair_textos_de_arquivo(nome, baixado.conteudo)
        textos.extend(t.texto for t in extraidos)

    return "\n".join(textos)[:CARACTERES_MAX_POR_DOCUMENTO]


def _montar_prompt(objeto_pncp: str, texto_documento: str) -> str:
    # PLACEHOLDER — ajuste a redação/tom conforme o estilo que você quer nas justificativas
    return f"""Você está avaliando se um edital de licitação pública é aderente ao portfólio da Aurora.

ESCOPO AURORA (categorias que tornam um edital aderente):
{ESCOPO_PRODUTO}

PADRÕES DE FALSO POSITIVO JÁ OBSERVADOS (o Score vetorial costuma errar nesses casos):
{PADROES_FALSO_POSITIVO}

OBJETO DA COMPRA (conforme listagem do PNCP, pode estar truncado ou genérico):
{objeto_pncp}

TEXTO DO EDITAL/TERMO DE REFERÊNCIA (fonte de verdade sobre o que está sendo contratado):
{texto_documento or "[não foi possível extrair texto do documento]"}

Julgue com base no conteúdo real acima, não no vocabulário do objeto do PNCP.
"""


def julgar_edital_via_api(
    client: anthropic.Anthropic, objeto_pncp: str, texto_documento: str
) -> dict[str, Any]:
    prompt = _montar_prompt(objeto_pncp, texto_documento)

    # checagem de tokens antes de enviar — nesta etapa (1 edital por chamada,
    # textos de ~1800-7000 chars) isso nunca deveria estourar limite algum,
    # mas fica como salvaguarda caso um documento fuja do padrão esperado
    contagem = client.messages.count_tokens(
        model=MODELO_ROUTINE, messages=[{"role": "user", "content": prompt}]
    )
    if contagem.input_tokens > 100_000:  # PLACEHOLDER — ajuste ao seu limite de orçamento
        raise ValueError(f"prompt com {contagem.input_tokens} tokens, acima do esperado")

    resposta = client.messages.create(
        model=MODELO_ROUTINE,
        max_tokens=MAX_TOKENS_ROUTINE,
        output_config={"format": {"type": "json_schema", "schema": VEREDITO_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    texto = next(b.text for b in resposta.content if b.type == "text")
    return json.loads(texto)


def rodar_etapa3_routine(data: str, top: int = TOP_N_REVISAO) -> None:
    client = anthropic.Anthropic()  # lê ANTHROPIC_API_KEY do ambiente

    selecionados = _carregar_top_selecionados(data, top)
    idx = _indexar_editais(data)

    justificativas: dict[str, dict[str, Any]] = {}
    for posicao, item in enumerate(selecionados, start=1):
        numero = item["numeroControlePNCP"]
        edital = idx.get(numero)
        if edital is None:
            print(f"  [{posicao}/{len(selecionados)}] {numero}: sem metadados, pulado")
            continue

        print(f"  [{posicao}/{len(selecionados)}] julgando {numero}...", flush=True)
        try:
            texto_documento = _texto_documento_principal(edital)
            veredito = julgar_edital_via_api(client, edital["objetoCompra"], texto_documento)
            justificativas[numero] = veredito
        except Exception as exc:  # nao deixa um edital com falha derrubar a rodada inteira
            print(f"  [erro] {numero}: {exc}")

    saida = DADOS / f"justificativas_{data}.json"
    saida.write_text(json.dumps(justificativas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Routine concluída: {len(justificativas)} editais julgados em {saida}")


def rodar_etapa4_envio(data: str, enviar: bool) -> None:
    comando = [sys.executable, "scripts/enviar_painel.py", "--data", data, "--top", str(TOP_N_REVISAO)]
    if enviar:
        comando.append("--enviar")
    subprocess.run(comando, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline completo de busca de editais.")
    parser.add_argument("--data", required=True, help="Data de referência (AAAA-MM-DD).")
    parser.add_argument("--enviar", action="store_true", help="Envia de fato ao Painel de Analistas (padrão: dry-run).")
    args = parser.parse_args()

    _carregar_dotenv()  # garante ANTHROPIC_API_KEY / EDITAIS_API_KEY disponíveis via .env

    print("=== Etapa 0: Coleta ===")
    rodar_etapa0_coleta(args.data)

    print("=== Etapa 1: Triagem ===")
    rodar_etapa1_triagem(args.data)

    print("=== Etapa 2: Análise profunda ===")
    rodar_etapa2_analise_profunda(args.data)

    print("=== Etapa 3: Routine (julgamento via API) ===")
    rodar_etapa3_routine(args.data)

    print("=== Etapa 4: Envio ao Painel de Analistas ===")
    rodar_etapa4_envio(args.data, enviar=args.enviar)


if __name__ == "__main__":
    main()
