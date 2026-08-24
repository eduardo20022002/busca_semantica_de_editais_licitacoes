from pathlib import Path

import pytest

from editais.transporte_gemini import criar_embedder_gemini


def test_sem_chave_no_ambiente_nem_em_env_falha_com_mensagem_clara(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # sem .env aqui, não deve vazar a chave real do dev

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        criar_embedder_gemini()
