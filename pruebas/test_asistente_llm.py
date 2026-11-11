"""Cliente del LLM (R 3.4) contra una API simulada con respx: no sale a la red ni gasta tokens."""

import json

import httpx
import pytest

from ingesta.asistente.llm import ClienteLLM, ErrorLLM, Uso

URL = "https://api.prueba/v1/chat/completions"


def _cliente(**kw) -> ClienteLLM:
    return ClienteLLM("clave-falsa", "modelo-x", "https://api.prueba/v1", **kw)


def test_herramientas_viajan_con_reasoning_effort_y_se_leen_las_llamadas(respx_mock):
    ruta = respx_mock.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "buscar_ofertas",
                                        "arguments": '{"consulta": "backend java"}',
                                    }
                                }
                            ],
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 2500,
                    "completion_tokens": 40,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )
    )
    r = _cliente().completar([{"role": "user", "content": "hola"}], [{"type": "function"}], "none")
    cuerpo = json.loads(ruta.calls.last.request.content)
    assert (
        cuerpo["reasoning_effort"] == "none" and cuerpo["tools"] and cuerpo["model"] == "modelo-x"
    )
    assert "temperature" not in cuerpo
    assert ruta.calls.last.request.headers["Authorization"] == "Bearer clave-falsa"
    assert r.llamadas[0].nombre == "buscar_ofertas"
    assert r.llamadas[0].argumentos == {"consulta": "backend java"}
    assert (r.uso.entrada, r.uso.salida, r.uso.razonamiento) == (2500, 40, 0)


def test_sin_razonamiento_no_se_envia_el_parametro(respx_mock):
    ruta = respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hola"}}]})
    )
    r = _cliente().completar([{"role": "user", "content": "hola"}])
    assert "reasoning_effort" not in json.loads(ruta.calls.last.request.content)
    assert r.texto == "hola" and r.llamadas == []


def test_error_400_no_se_reintenta(respx_mock):
    ruta = respx_mock.post(URL).mock(return_value=httpx.Response(400, json={"error": "x"}))
    with pytest.raises(ErrorLLM, match="HTTP 400"):
        _cliente(reintentos=2).completar([{"role": "user", "content": "hola"}])
    assert ruta.call_count == 1


def test_streaming_entrega_el_texto_y_suma_el_uso(respx_mock):
    eventos = [
        {"choices": [{"delta": {"content": "Hola "}}]},
        {"choices": [{"delta": {"content": "mundo"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 3000,
                "completion_tokens": 200,
                "completion_tokens_details": {"reasoning_tokens": 64},
            },
        },
    ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in eventos) + "data: [DONE]\n\n"
    ruta = respx_mock.post(URL).mock(return_value=httpx.Response(200, text=sse))
    uso = Uso()
    texto = "".join(_cliente().completar_stream([{"role": "user", "content": "x"}], uso, "low"))
    cuerpo = json.loads(ruta.calls.last.request.content)
    assert texto == "Hola mundo" and cuerpo["stream"] and cuerpo["reasoning_effort"] == "low"
    assert (uso.entrada, uso.salida, uso.razonamiento) == (3000, 200, 64)
