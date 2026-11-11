"""Cliente mínimo de una API compatible con «chat completions» (OpenAI u otra).

Solo se envían `model`, `messages` y, si se pide, `response_format`: los modelos de razonamiento
rechazan `temperature` y otros parámetros de muestreo.
"""

import time
from dataclasses import dataclass

import httpx


class ErrorLLM(RuntimeError):
    """La API del modelo respondió con un error o no respondió."""


@dataclass(frozen=True)
class RespuestaLLM:
    texto: str
    tokens_entrada: int
    tokens_salida: int


class ClienteLLM:
    def __init__(
        self,
        api_key: str,
        modelo: str,
        base_url: str = "https://api.openai.com/v1",
        tiempo_limite_s: float = 90.0,
        reintentos: int = 2,
    ):
        self.modelo = modelo
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._cabeceras = {"Authorization": f"Bearer {api_key}"}
        self._http = httpx.Client(timeout=tiempo_limite_s)
        self._reintentos = reintentos

    def completar(self, mensajes: list[dict[str, str]], json: bool = False) -> RespuestaLLM:
        cuerpo: dict = {"model": self.modelo, "messages": mensajes}
        if json:
            cuerpo["response_format"] = {"type": "json_object"}
        ultimo = ""
        for intento in range(self._reintentos + 1):
            try:
                r = self._http.post(self._url, headers=self._cabeceras, json=cuerpo)
            except httpx.HTTPError as e:
                ultimo = f"sin conexión con la API del modelo ({type(e).__name__})"
            else:
                if r.status_code == 200:
                    datos = r.json()
                    uso = datos.get("usage") or {}
                    return RespuestaLLM(
                        texto=(datos["choices"][0]["message"].get("content") or "").strip(),
                        tokens_entrada=uso.get("prompt_tokens", 0),
                        tokens_salida=uso.get("completion_tokens", 0),
                    )
                ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            if intento < self._reintentos:
                time.sleep(2 * (intento + 1))
        raise ErrorLLM(ultimo)
