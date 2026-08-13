from perfil_store import _construir_perfil_resumido


def test_perfil_resumido_incluye_datos_basicos():
    perfil = {
        "nombre": "Ana Perez",
        "edad": 28,
        "ciudad": "Santiago",
        "comuna": "Nunoa",
        "estudios": [{"titulo": "Tecnico en Administracion"}],
        "perfil_profesional": "Resumen de prueba",
        "habilidades": ["Excel", "Atencion al cliente", "Ventas"],
        "idiomas": [{"idioma": "Espanol", "nivel": "Nativo"}],
    }
    resumen = _construir_perfil_resumido(perfil)
    assert "Ana Perez" in resumen
    assert "Santiago, Nunoa" in resumen
    assert "Tecnico en Administracion" in resumen
    assert "Espanol Nativo" in resumen


def test_perfil_resumido_sin_estudios_no_revienta():
    perfil = {"nombre": "Sin Estudios"}
    resumen = _construir_perfil_resumido(perfil)
    assert "Sin Estudios" in resumen
    assert "Profesion: \n" in resumen


def test_perfil_resumido_trunca_perfil_profesional_largo():
    perfil = {"nombre": "X", "perfil_profesional": "a" * 500}
    resumen = _construir_perfil_resumido(perfil)
    linea_perfil = [l for l in resumen.splitlines() if l.startswith("Perfil:")][0]
    assert len(linea_perfil) <= len("Perfil: ") + 300
