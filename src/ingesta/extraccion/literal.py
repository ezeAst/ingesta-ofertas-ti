"""Vía literal: términos canónicos y variantes literales del vocabulario con PhraseMatcher.

Reglas (Anexo J §6): se prefiere la coincidencia más larga; las siglas respetan mayúsculas;
toda coincidencia respeta límites de palabra (la comparación es por tokens), y los términos
cortos con otra lectura posible solo cuentan junto a otro término o a una palabra de contexto.
Las variantes descriptivas no se usan aquí: solo participan en la vía semántica.
"""

from spacy.language import Language
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc

from ingesta.config import ParamsTerminosContexto
from ingesta.extraccion import Coincidencia
from ingesta.vocabulario import Vocabulario


def es_sigla(forma: str) -> bool:
    """Siglas y formas muy cortas se comparan con mayúsculas exactas («SQL», «R», «Go»)."""
    return forma.isupper() or len(forma) <= 2


class ComparadorLiteral:
    def __init__(self, vocab: Vocabulario, nlp: Language, contexto: ParamsTerminosContexto):
        self._exacto = PhraseMatcher(nlp.vocab, attr="ORTH")
        self._minusculas = PhraseMatcher(nlp.vocab, attr="LOWER")
        self._strings = nlp.vocab.strings
        self._categoria = {}
        for t in vocab.terminos:
            formas = [t["nombre"], *t["literales"]]
            self._categoria[t["nombre"]] = t["categoria"]
            siglas = [nlp.make_doc(f) for f in formas if es_sigla(f)]
            resto = [nlp.make_doc(f) for f in formas if not es_sigla(f)]
            if siglas:
                self._exacto.add(t["nombre"], siglas)
            if resto:
                self._minusculas.add(t["nombre"], resto)
        self._con_contexto = set(contexto.terminos)
        self._palabras_contexto = {p.lower() for p in contexto.palabras_contexto}

    def buscar(self, docs: list[Doc]) -> list[Coincidencia]:
        resultado: list[Coincidencia] = []
        for indice, doc in enumerate(docs):
            resultado.extend(self._buscar_en(indice, doc))
        return resultado

    def _buscar_en(self, indice: int, doc: Doc) -> list[Coincidencia]:
        tramos = {
            (inicio, fin, self._strings[clave])
            for matcher in (self._exacto, self._minusculas)
            for clave, inicio, fin in matcher(doc)
        }
        # Coincidencia más larga: se descarta un tramo contenido en otro más largo. Dos términos
        # con el mismo tramo (variante colisionada, p. ej. EKS) se conservan los dos (D11).
        maximos = [
            (i, f, t)
            for i, f, t in tramos
            if not any(i2 <= i and f <= f2 and (f2 - i2) > (f - i) for i2, f2, _ in tramos)
        ]
        terminos = {t for _, _, t in maximos}
        hay_palabra_contexto = any(tok.lower_ in self._palabras_contexto for tok in doc)
        coincidencias = []
        for i, f, termino in sorted(maximos):
            if termino in self._con_contexto and not (hay_palabra_contexto or terminos - {termino}):
                continue
            tramo = doc[i:f]
            coincidencias.append(
                Coincidencia(
                    termino=termino,
                    categoria=self._categoria[termino],
                    unidad=indice,
                    inicio=tramo.start_char,
                    fin=tramo.end_char,
                    texto=tramo.text,
                )
            )
        return coincidencias
