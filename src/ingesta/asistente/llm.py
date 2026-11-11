"""Cliente de una API compatible con «chat completions» (OpenAI u otra).

Solo se envían `model`, `messages`, `tools` y `stream`: los modelos de razonamiento rechazan
`temperature` y otros parámetros de muestreo. Cada respuesta informa los tokens, incluidos los de
razonamiento cuando la API los reporta (se cobran como salida).
"""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx


class ErrorLLM(RuntimeError):
    """La API del modelo respondió con un error o no respondió."""


@dataclass(frozen=True)
class LlamadaHerramienta:
    nombre: str
    argumentos: dict


@dataclass
class Uso:
    entrada: int = 0
    salida: int = 0
    razonamiento: int = 0  # ya incluido en `salida`

    @classmethod
    def desde_api(cls, uso: dict | None) -> "Uso":
        uso = uso or {}
        detalle = uso.get("completion_tokens_details") or {}
        return cls(
            entrada=uso.get("prompt_tokens", 0) or 0,
            salida=uso.get("completion_tokens", 0) or 0,
            razonamiento=detalle.get("reasoning_tokens", 0) or 0,
        )

    def sumar(self, otro: "Uso") -> None:
        self.entrada += otro.entrada
        self.salida += otro.salida
        self.razonamiento += otro.razonamiento


@dataclass
class RespuestaLLM:
    texto: str
    llamadas: list[LlamadaHerramienta] = field(default_factory=list)
    uso: Uso = field(default_factory=Uso)


_REINTENTABLES = (429, 500, 502, 503, 504)


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

    def completar(
        self, mensajes: list[dict], herramientas: list[dict] | None = None
    ) -> RespuestaLLM:
        cuerpo: dict = {"model": self.modelo, "messages": mensajes}
        if herramientas:
            cuerpo["tools"] = herramientas
        datos = self._con_reintentos(
            lambda: self._http.post(self._url, headers=self._cabeceras, json=cuerpo)
        ).json()
        mensaje = datos["choices"][0]["message"]
        llamadas = []
        for llamada in mensaje.get("tool_calls") or []:
            funcion = llamada.get("function") or {}
            try:
                argumentos = json.loads(funcion.get("arguments") or "{}")
            except json.JSONDecodeError:
                argumentos = {}
            llamadas.append(
                LlamadaHerramienta(
                    funcion.get("name", ""), argumentos if isinstance(argumentos, dict) else {}
                )
            )
        return RespuestaLLM(
            texto=(mensaje.get("content") or "").strip(),
            llamadas=llamadas,
            uso=Uso.desde_api(datos.get("usage")),
        )

    def completar_stream(self, mensajes: list[dict], uso: Uso) -> Iterator[str]:
        """Entrega el texto a medida que llega; al terminar, suma el consumo en `uso`."""
        cuerpo = {
            "model": self.modelo,
            "messages": mensajes,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        ultimo = ""
        emitido = False  # tras emitir texto ya no se reintenta: se duplicaría la respuesta
        for intento in range(self._reintentos + 1):
            try:
                with self._http.stream(
                    "POST", self._url, headers=self._cabeceras, json=cuerpo
                ) as r:
                    if r.status_code != 200:
                        r.read()
                        ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
                        if r.status_code in _REINTENTABLES and intento < self._reintentos:
                            time.sleep(2 * (intento + 1))
                            continue
                        raise ErrorLLM(ultimo)
                    for linea in r.iter_lines():
                        if not linea.startswith("data:"):
                            continue
                        carga = linea[5:].strip()
                        if carga == "[DONE]":
                            break
                        evento = json.loads(carga)
                        if evento.get("usage"):
                            uso.sumar(Uso.desde_api(evento["usage"]))
                        for opcion in evento.get("choices") or []:
                            texto = (opcion.get("delta") or {}).get("content")
                            if texto:
                                emitido = True
                                yield texto
                    return
            except httpx.HTTPError as e:
                ultimo = f"sin conexión con la API del modelo ({type(e).__name__})"
                if not emitido and intento < self._reintentos:
                    time.sleep(2 * (intento + 1))
                    continue
        raise ErrorLLM(ultimo)

    def _con_reintentos(self, enviar) -> httpx.Response:
        ultimo = ""
        for intento in range(self._reintentos + 1):
            try:
                r = enviar()
            except httpx.HTTPError as e:
                ultimo = f"sin conexión con la API del modelo ({type(e).__name__})"
            else:
                if r.status_code == 200:
                    return r
                ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in _REINTENTABLES:
                    break
            if intento < self._reintentos:
                time.sleep(2 * (intento + 1))
        raise ErrorLLM(ultimo)
