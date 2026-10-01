"""Normalizador y segmentador (Anexo J §5): texto limpio y unidades de requisito."""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

SECCIONES_BUMERAN = (
    "Conocimientos y Certificaciones Indispensables",
    "Conocimientos y Certificaciones Deseables",
    "Habilidades Blandas",
)

# Beneficios, condiciones del puesto y presentación de la empresa: no describen competencias y
# la vía semántica las ignora (con 0,85 aceptaba «Bono de alimentación» como SOAP). La zona abre
# con uno de estos títulos y cierra con un título de requisitos o una sección de Bumeran.
SECCION_EXCLUIDA = "Beneficios y empresa"
_RE_TITULO_EXCLUIDO = re.compile(
    r"^[¿¡\W]*(?:qu[eé] (?:te )?ofrecemos|te ofrecemos|ofrecemos|beneficios"
    r"|qu[eé] puedes esperar|por qu[eé] (?:ser parte|sumarte|unirte|trabajar|elegirnos)"
    r"|sobre nosotros|qui[eé]nes somos|nuestra empresa|condiciones del puesto"
    r"|detalles del puesto|horario|lugar de trabajo|modalidad\s*:)",
    re.IGNORECASE,
)
_RE_TITULO_REQUISITOS = re.compile(
    r"^[¿¡\W]*(?:requisitos|requerimientos|funciones|principales funciones|responsabilidades"
    r"|principales responsabilidades|conocimientos|competencias|habilidades|misi[oó]n"
    r"|objetivo|perfil|formaci[oó]n|experiencia|ideal si|en esta funci[oó]n|qu[eé] har[aá]s"
    r"|qu[eé] buscamos|buscamos|cu[aá]l ser[aá] tu|deseable|indispensable)",
    re.IGNORECASE,
)

_MARCA_SECCION = "\x00SECCION:"
_RE_SECCION = re.compile(
    r"(" + "|".join(re.escape(s) for s in SECCIONES_BUMERAN) + r")\s*:", re.IGNORECASE
)
_MAYUSCULA = "A-ZÁÉÍÓÚÑ¿¡"
# Frases que Bumeran deja pegadas al quitar el marcado: «¿Qué harás?Diseñar», «(Jobs)Conoc...»,
# «educativos.Actualmente», «vulnerabilidades.CONOCIMIENTOS TÉCNICOS». No se corta entre
# minúscula y mayúscula a secas para no partir nombres como «PySpark» o «JavaScript», ni tras un
# punto seguido de solo dos mayúsculas («Node.JS»).
_RE_PEGADO = re.compile(
    rf"(?<=[?!)])(?=[{_MAYUSCULA}])"
    rf"|(?<=[a-záéíóúñ]\.)(?=[¿¡]|[A-ZÁÉÍÓÚÑ][a-záéíóúñ]|[A-ZÁÉÍÓÚÑ]{{3,}})"
)
_RE_VINETA = re.compile(r"^\s*(?:[-*•·●▪◦►✓]+|\d+[.)])\s*")
_RE_ORACION = re.compile(rf"(?<=[.!?;])\s+(?=[{_MAYUSCULA}])")
_RE_ESPACIOS = re.compile(r"[ \t\u00a0]+")


# Emojis y pictogramas: bloques de Unicode de emoji, símbolos y dingbats (✅, ☁), banderas,
# modificadores de tono de piel, selector de variación y unión de ancho cero.
_RE_EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoji, pictogramas, banderas y tonos de piel
    "\u2600-\u27bf"  # símbolos varios y dingbats
    "\u2b00-\u2bff"  # flechas y estrellas (⭐)
    "\u2300-\u23ff"  # técnicos (⌛, ⏰)
    "\ufe0f\u200d\u20e3"  # selector de variación, unión de ancho cero, tecla
    "]+"
)


def quitar_emojis(texto: str) -> str:
    """Reemplaza cada emoji (o secuencia de emojis) por un espacio."""
    return _RE_EMOJI.sub(" ", texto)


@dataclass(frozen=True)
class Unidad:
    texto: str
    seccion: str | None = None


def html_a_texto(html: str) -> str:
    """Quita el marcado conservando los cortes de párrafo, salto y viñeta como líneas."""
    sopa = BeautifulSoup(html or "", "lxml")
    for br in sopa.find_all("br"):
        br.replace_with("\n")
    texto = sopa.get_text("\n")
    lineas = (_RE_ESPACIOS.sub(" ", linea).strip() for linea in texto.splitlines())
    return "\n".join(linea for linea in lineas if linea)


def texto_plano(texto: str) -> str:
    """Texto limpio para guardar en `descripcion`: una línea por bloque, sin espacios repetidos."""
    lineas = (_RE_ESPACIOS.sub(" ", linea).strip() for linea in texto.splitlines())
    return "\n".join(linea for linea in lineas if linea)


def texto_legible(texto: str, portal: str) -> str:
    """Descripción limpia para `descripcion` (decisión I4). En Bumeran se reconstruyen los cortes
    de línea que la interfaz pierde y los títulos de sección se conservan como líneas."""
    if portal == "Bumeran":
        texto = _preparar_bumeran(texto)
        texto = "\n".join(
            f"{linea.removeprefix(_MARCA_SECCION)}:" if linea.startswith(_MARCA_SECCION) else linea
            for linea in texto.splitlines()
        )
    return texto_plano(texto)


def _preparar_bumeran(texto: str) -> str:
    texto = _RE_SECCION.sub(lambda m: f"\n{_MARCA_SECCION}{_canonica(m.group(1))}\n", texto)
    texto = re.sub(r"[ \t\u00a0]{2,}", "\n", texto)
    return _RE_PEGADO.sub("\n", texto)


def _canonica(nombre: str) -> str:
    return next(s for s in SECCIONES_BUMERAN if s.lower() == nombre.lower())


def segmentar(texto: str, portal: str) -> list[Unidad]:
    if portal == "Bumeran":
        texto = _preparar_bumeran(texto)
    unidades: list[Unidad] = []
    seccion: str | None = None
    excluida = False
    for linea in texto.splitlines():
        if linea.startswith(_MARCA_SECCION):
            seccion = linea.removeprefix(_MARCA_SECCION)
            excluida = False
            continue
        linea = _RE_VINETA.sub("", _RE_ESPACIOS.sub(" ", linea)).strip()
        for frase in _RE_ORACION.split(linea):
            frase = frase.strip()
            if len(re.findall(r"\w", frase)) >= 2:
                excluida = _zona_excluida(frase, excluida)
                unidades.append(Unidad(frase, SECCION_EXCLUIDA if excluida else seccion))
    return unidades


def _zona_excluida(frase: str, actual: bool) -> bool:
    """Si la frase abre, cierra o continúa la zona de beneficios y empresa."""
    if _RE_TITULO_EXCLUIDO.match(frase):
        return True
    if _RE_TITULO_REQUISITOS.match(frase) or _es_titulo_suelto(frase):
        return False
    return actual


def _es_titulo_suelto(frase: str) -> bool:
    """Título en su propia línea: «Requisitos:», «¿Qué buscamos?» o «CONOCIMIENTOS TÉCNICOS»."""
    if len(frase.split()) > 8:
        return False
    return frase.endswith((":", "?")) or frase.startswith("¿") or frase.isupper()
