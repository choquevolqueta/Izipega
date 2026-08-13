from cv_export import _vinetas_de
from ia_logic import _texto_completo_campo
from models import Campo, CampoMeta


def test_vinetas_de_usa_lista_si_existe():
    e = {"vinetas": ["Hice A.", "Hice B."], "descripcion": "esto no deberia usarse"}
    assert _vinetas_de(e) == ["Hice A.", "Hice B."]


def test_vinetas_de_parte_descripcion_por_oraciones():
    e = {"descripcion": "Hice A. Hice B; Hice C."}
    vinetas = _vinetas_de(e)
    assert vinetas == ["Hice A.", "Hice B;", "Hice C."]


def test_vinetas_de_vacio_sin_datos():
    assert _vinetas_de({}) == []


def test_texto_completo_campo_concatena_meta():
    campo = Campo(
        id="1", tipo="text", label="Telefono",
        meta=CampoMeta(placeholder="Ej: +56911112222", name="phone", id="tel-input"),
    )
    texto = _texto_completo_campo(campo)
    assert "Telefono" in texto
    assert "phone" in texto
    assert "tel-input" in texto


def test_texto_completo_campo_sin_meta():
    campo = Campo(id="1", tipo="text", label="Solo label")
    assert _texto_completo_campo(campo) == "Solo label"
