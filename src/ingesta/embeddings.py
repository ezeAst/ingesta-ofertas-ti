"""Cliente del servicio Text Embeddings Inference (decisión I15).

TEI no añade los prefijos de E5 («query: », «passage: »): los pone quien llama.
"""

import httpx
import numpy as np


class ClienteTEI:
    def __init__(self, url: str, lote: int = 32, tiempo_limite_s: float = 120.0):
        self._url = url.rstrip("/")
        self._lote = lote  # TEI acepta 32 entradas por solicitud por defecto
        self._http = httpx.Client(timeout=tiempo_limite_s)

    def info(self) -> dict:
        respuesta = self._http.get(f"{self._url}/info")
        respuesta.raise_for_status()
        return respuesta.json()

    def vectorizar(self, textos: list[str]) -> np.ndarray:
        if not textos:
            return np.zeros((0, 0))
        partes = []
        for i in range(0, len(textos), self._lote):
            respuesta = self._http.post(
                f"{self._url}/embed",
                json={"inputs": textos[i : i + self._lote], "normalize": True, "truncate": True},
            )
            respuesta.raise_for_status()
            partes.append(np.asarray(respuesta.json(), dtype=np.float32))
        return np.vstack(partes)

    def contar_tokens(self, textos: list[str]) -> list[int]:
        """Tokens de cada texto con el tokenizador del modelo, incluidos los especiales."""
        conteos: list[int] = []
        for i in range(0, len(textos), self._lote):
            respuesta = self._http.post(
                f"{self._url}/tokenize",
                json={"inputs": textos[i : i + self._lote], "add_special_tokens": True},
            )
            respuesta.raise_for_status()
            conteos.extend(len(tokens) for tokens in respuesta.json())
        return conteos
