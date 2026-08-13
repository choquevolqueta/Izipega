import perfil_store
from ia_logic import respuesta_directa


def _set_perfil(monkeypatch, **kwargs):
    base = {
        "telefono": "", "email": "", "ciudad": "", "comuna": "",
        "nacionalidad": "", "disponibilidad": "", "expectativa_sueldo": "",
        "respuestas_extra": {}, "redes": {"linkedin": "", "portafolio_web": "", "behance": ""},
    }
    base.update(kwargs)
    monkeypatch.setattr(perfil_store, "PERFIL", base)
    return base


def test_telefono(monkeypatch):
    _set_perfil(monkeypatch, telefono="+56 9 1111 2222")
    assert respuesta_directa("Numero de telefono") == "+56 9 1111 2222"


def test_correo(monkeypatch):
    _set_perfil(monkeypatch, email="test@example.com")
    assert respuesta_directa("Tu correo electronico") == "test@example.com"


def test_datos_de_contacto_combinado_prioriza_sobre_matches_individuales(monkeypatch):
    _set_perfil(monkeypatch, telefono="+56911112222", email="a@b.com")
    resp = respuesta_directa("Datos de contacto")
    assert resp == "+56911112222 / a@b.com"


def test_disponibilidad(monkeypatch):
    _set_perfil(monkeypatch, disponibilidad="inmediata")
    assert respuesta_directa("Disponibilidad para trabajar") == "inmediata"


def test_sueldo(monkeypatch):
    _set_perfil(monkeypatch, expectativa_sueldo="a convenir")
    assert respuesta_directa("Pretension de renta") == "a convenir"


def test_comuna(monkeypatch):
    _set_perfil(monkeypatch, comuna="Providencia")
    assert respuesta_directa("Comuna donde vives") == "Providencia"


def test_ciudad(monkeypatch):
    _set_perfil(monkeypatch, ciudad="Santiago")
    assert respuesta_directa("En que ciudad vives") == "Santiago"


def test_linkedin(monkeypatch):
    _set_perfil(monkeypatch, redes={"linkedin": "https://linkedin.com/in/x", "portafolio_web": "", "behance": ""})
    assert respuesta_directa("Tu perfil de LinkedIn") == "https://linkedin.com/in/x"


def test_portafolio(monkeypatch):
    _set_perfil(monkeypatch, redes={"linkedin": "", "portafolio_web": "https://miportfolio.com", "behance": ""})
    assert respuesta_directa("Sitio web personal") == "https://miportfolio.com"


def test_licencia_conducir(monkeypatch):
    _set_perfil(monkeypatch, respuestas_extra={"licencia_conducir": "Si, clase B"})
    assert respuesta_directa("Tienes licencia de conducir") == "Si, clase B"


def test_sin_match_devuelve_none(monkeypatch):
    _set_perfil(monkeypatch)
    assert respuesta_directa("Cual es tu color favorito") is None


def test_campo_vacio_en_perfil_devuelve_none_no_string_vacio(monkeypatch):
    _set_perfil(monkeypatch, telefono="")
    assert respuesta_directa("Telefono de contacto") is None
