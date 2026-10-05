"""Vía léxica (por descarte): palabras que ni el diccionario ni los embeddings reconocen.

De cada unidad se quitan las palabras que forman parte de un término canónico o de una variante
literal, las palabras del español y las palabras comunes del inglés. Lo que queda suele ser una
herramienta o tecnología que falta en el vocabulario («Lambda», «Terraform», «Bizagi»).

Una palabra cuenta como español si su frecuencia (escala Zipf de `wordfreq`) en español supera un
mínimo y además supera a la del inglés por un margen: «afines» (3,8 en español, 0 en inglés) se
descarta, mientras que «Lambda» (2,7 / 3,1) o «Kafka» (3,2 / 3,0) se conservan porque su uso es
igual o mayor en inglés. No se usa la pertenencia a un diccionario del español: «lambda», «swift»
o «spring» son palabras del idioma y se perderían.

Las palabras sobrevivientes contiguas (separadas solo por espacios) forman un solo tramo
(«Apache Airflow»). Los candidatos se encolan sin término cercano ni puntaje; el panel los agrupa
por tramo y muestra cuántos avisos los mencionan.
"""

import re

from wordfreq import zipf_frequency

from ingesta.config import ParamsViaLexica
from ingesta.extraccion import Candidato
from ingesta.normalizacion import SECCION_EXCLUIDA, Unidad
from ingesta.vocabulario import Vocabulario

_LETRA = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
_RE_ENTIDAD = re.compile(r"&#x?[0-9a-fA-F]+;?|&[a-z]+;")
# Palabra: empieza con letra; admite «#», «+» y puntos o guiones internos (C#, Node.js, T-SQL).
_RE_PALABRA = re.compile(rf"[{_LETRA}][\w#+]*(?:[.\-'][\w#+]+)*")
# Punto que pega dos oraciones: «RxJS.Desarrollo», «sprint.6». No parte «ASP.NET» ni «Node.js».
_RE_PUNTO_PEGADO = re.compile(r"(?<=\w)\.(?=[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2}|\d)")
# Trozos de una palabra en CamelCase: «ScrumExperiencia» → Scrum, Experiencia.
_RE_TROZO = re.compile(
    r"[A-ZÁÉÍÓÚÜÑ]+(?=[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ])|[A-ZÁÉÍÓÚÜÑ]?[a-záéíóúüñ]+|[A-ZÁÉÍÓÚÜÑ]+"
)
_RE_VERSION = re.compile(r"^v?\d+(?:\.\d+)*$", re.IGNORECASE)


class ComparadorLexico:
    def __init__(self, vocab: Vocabulario, params: ParamsViaLexica):
        self._params = params
        self._del_vocabulario = {
            palabra.lower()
            for t in vocab.terminos
            for forma in (t["nombre"], *t["literales"])
            for palabra in _RE_PALABRA.findall(forma)
        }

    def es_espanol(self, palabra: str) -> bool:
        es = zipf_frequency(palabra, "es")
        return (
            es >= self._params.zipf_minimo_espanol
            and es >= zipf_frequency(palabra, "en") + self._params.margen_espanol
        )

    def es_conocida(self, palabra: str) -> bool:
        """Del vocabulario, del español o común en inglés: no es candidata."""
        minuscula = palabra.lower()
        return (
            minuscula in self._del_vocabulario
            or self.es_espanol(minuscula)
            or zipf_frequency(minuscula, "en") >= self._params.zipf_maximo_ingles
        )

    def evaluar(self, unidades: list[Unidad]) -> list[Candidato]:
        candidatos: dict[str, Candidato] = {}
        for i, unidad in enumerate(unidades):
            if unidad.seccion == SECCION_EXCLUIDA:
                continue
            for tramo in self._tramos(unidad.texto):
                candidatos.setdefault(
                    tramo.lower(), Candidato(i, unidad.texto, tramo, None, None, origen="lexico")
                )
        return list(candidatos.values())

    def _tramos(self, texto: str) -> list[str]:
        """Palabras desconocidas, unidas cuando solo las separan espacios."""
        texto = _RE_PUNTO_PEGADO.sub(" ", _RE_ENTIDAD.sub(" ", texto))
        tramos: list[str] = []
        actual: list[str] = []
        fin_anterior = 0
        for m in _RE_PALABRA.finditer(texto):
            piezas = self._desconocidas(m.group())
            entera = piezas == [m.group()]
            contigua = entera and texto[fin_anterior : m.start()].isspace()
            if actual and not contigua:
                tramos.append(" ".join(actual))
                actual = []
            if entera:
                actual.append(m.group())
                fin_anterior = m.end()
            else:  # palabra conocida o pegada a otra: corta el tramo
                tramos.extend(piezas)
        if actual:
            tramos.append(" ".join(actual))
        return tramos

    def _desconocidas(self, palabra: str) -> list[str]:
        """La palabra si es desconocida; si viene pegada a otra en CamelCase («ScrumExperiencia»,
        «CertificacionesAWS»), se separan los trozos del español y se evalúa el resto."""
        if len(palabra) < 2 or _RE_VERSION.match(palabra):
            return []
        trozos = _RE_TROZO.findall(palabra) if palabra.isalpha() else []
        if len(trozos) < 2:
            return [] if self.es_conocida(palabra) else [palabra]
        fragmentos, actual = [], ""
        for trozo in trozos:
            if len(trozo) >= 4 and self.es_espanol(trozo.lower()):
                fragmentos.append(actual)
                actual = ""
            else:
                actual += trozo
        fragmentos.append(actual)
        if fragmentos == [palabra]:  # «JavaScript», «PostgreSQL»: nada que separar
            return [] if self.es_conocida(palabra) else [palabra]
        return [f for f in fragmentos if len(f) >= 2 and not self.es_conocida(f)]
