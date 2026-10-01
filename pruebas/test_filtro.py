"""CP-17: filtro de pertinencia (riesgo R3), por competencias técnicas literales."""

from ingesta.filtro import es_de_ti


def test_cp17_umbral_de_dos_tecnicas():
    assert es_de_ti({"Python"}, minimo=2) is False
    assert es_de_ti({"Python", "SQL"}, minimo=2) is True
    assert es_de_ti({"Python", "SQL", "Git"}, minimo=2) is True
    assert es_de_ti(set(), minimo=2) is False
