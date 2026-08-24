import threading

import editais.transporte_http as th


def test_sessao_e_reaproveitada_entre_chamadas() -> None:
    # A razão de existir da sessão compartilhada: sem ela cada requests.get
    # abre conexão nova e paga handshake TLS — 744 vezes numa rodada real.
    th.reiniciar_sessao()

    assert th.obter_sessao() is th.obter_sessao()


def test_pool_acomoda_o_numero_de_downloads_simultaneos() -> None:
    # Pool menor que a concorrência faz as threads excedentes ou serializarem
    # na fila do pool ou descartarem conexão a cada uso ("Connection pool is
    # full"), devolvendo justamente o handshake que a sessão veio eliminar.
    th.reiniciar_sessao(tamanho_pool=16)

    adaptador = th.obter_sessao().get_adapter("https://pncp.gov.br/")

    assert adaptador._pool_maxsize == 16
    assert adaptador._pool_connections == 16


def test_reiniciar_sessao_troca_a_sessao_anterior() -> None:
    th.reiniciar_sessao(tamanho_pool=4)
    primeira = th.obter_sessao()

    th.reiniciar_sessao(tamanho_pool=8)

    assert th.obter_sessao() is not primeira
    assert th.obter_sessao().get_adapter("https://pncp.gov.br/")._pool_maxsize == 8


def test_sessao_e_criada_uma_vez_so_sob_concorrencia() -> None:
    # Vários workers começam juntos e chamam obter_sessao() ao mesmo tempo: sem
    # exclusão mútua, cada um constrói a sua e o pool compartilhado deixa de
    # existir de fato.
    th.reiniciar_sessao()
    sessoes: list[object] = []
    trava = threading.Lock()
    largada = threading.Barrier(8)

    def pegar() -> None:
        largada.wait()
        sessao = th.obter_sessao()
        with trava:
            sessoes.append(sessao)

    threads = [threading.Thread(target=pegar) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(id(s) for s in sessoes)) == 1
