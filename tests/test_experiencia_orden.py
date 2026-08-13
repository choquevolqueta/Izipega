from cv_export import ordenar_experiencia_reciente


def test_ordena_de_mas_reciente_a_mas_antigua():
    exps = [
        {"cargo": "A", "periodo": "Enero 2020 - Diciembre 2021"},
        {"cargo": "B", "periodo": "Marzo 2023 - Actualidad"},
        {"cargo": "C", "periodo": "Junio 2022"},
    ]
    resultado = ordenar_experiencia_reciente(exps)
    assert [e["cargo"] for e in resultado] == ["B", "C", "A"]


def test_actualidad_pesa_como_mas_reciente_sin_importar_anio_inicio():
    exps = [
        {"cargo": "Viejo con fin fijo", "periodo": "Enero 2024 - Diciembre 2024"},
        {"cargo": "Actual", "periodo": "Enero 2019 - Presente"},
    ]
    resultado = ordenar_experiencia_reciente(exps)
    assert resultado[0]["cargo"] == "Actual"


def test_sin_anios_no_revienta_y_queda_al_final():
    exps = [
        {"cargo": "Con fecha", "periodo": "2023"},
        {"cargo": "Sin fecha", "periodo": "freelance ocasional"},
    ]
    resultado = ordenar_experiencia_reciente(exps)
    assert resultado[0]["cargo"] == "Con fecha"
    assert resultado[1]["cargo"] == "Sin fecha"


def test_no_es_lista_devuelve_tal_cual():
    assert ordenar_experiencia_reciente(None) is None
    assert ordenar_experiencia_reciente("no es lista") == "no es lista"
