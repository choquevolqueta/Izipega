import perfil_store


def test_guardar_y_cargar_historial(tmp_path, monkeypatch):
    monkeypatch.setattr(perfil_store, "HISTORIAL_PATH", tmp_path / "historial_keywords.json")

    assert perfil_store.cargar_historial() == []

    perfil_store.guardar_en_historial({
        "cargo_objetivo": "Vendedor",
        "empresa": "Tienda X",
        "score_idoneidad": 70,
        "keywords_faltantes": ["Excel avanzado", "SAP"],
        "keywords_coincidentes": ["Atencion al cliente"],
    })

    historial = perfil_store.cargar_historial()
    assert len(historial) == 1
    assert historial[0]["cargo_objetivo"] == "Vendedor"
    assert historial[0]["keywords_faltantes"] == ["Excel avanzado", "SAP"]


def test_guardar_en_historial_ignora_entrada_sin_cargo(tmp_path, monkeypatch):
    monkeypatch.setattr(perfil_store, "HISTORIAL_PATH", tmp_path / "historial_keywords.json")
    perfil_store.guardar_en_historial({"cargo_objetivo": "", "keywords_faltantes": ["X"]})
    assert perfil_store.cargar_historial() == []


def test_historial_es_ring_buffer_de_tamano_maximo(tmp_path, monkeypatch):
    monkeypatch.setattr(perfil_store, "HISTORIAL_PATH", tmp_path / "historial_keywords.json")
    monkeypatch.setattr(perfil_store, "HISTORIAL_MAX", 3)

    for i in range(5):
        perfil_store.guardar_en_historial({"cargo_objetivo": f"Cargo {i}", "keywords_faltantes": []})

    historial = perfil_store.cargar_historial()
    assert len(historial) == 3
    assert [e["cargo_objetivo"] for e in historial] == ["Cargo 2", "Cargo 3", "Cargo 4"]


def test_cargar_historial_con_archivo_corrupto_devuelve_lista_vacia(tmp_path, monkeypatch):
    p = tmp_path / "historial_keywords.json"
    p.write_text("esto no es json valido", encoding="utf-8")
    monkeypatch.setattr(perfil_store, "HISTORIAL_PATH", p)
    assert perfil_store.cargar_historial() == []


def test_top_keywords_faltantes_cuenta_y_ordena_por_frecuencia():
    historial = [
        {"keywords_faltantes": ["Excel", "SAP"]},
        {"keywords_faltantes": ["excel", "Ingles"]},
        {"keywords_faltantes": ["Excel"]},
    ]
    top = perfil_store.top_keywords_faltantes(historial)
    assert top[0]["keyword"] == "Excel"
    assert top[0]["veces"] == 3
    veces_por_kw = {k["keyword"].lower(): k["veces"] for k in top}
    assert veces_por_kw["sap"] == 1
    assert veces_por_kw["ingles"] == 1


def test_top_keywords_faltantes_filtra_por_score_minimo():
    historial = [
        {"score_idoneidad": 90, "keywords_faltantes": ["Atencion al cliente"]},
        {"score_idoneidad": 20, "keywords_faltantes": ["Soldadura"]},  # rubro sin relacion, score bajo
        {"score_idoneidad": None, "keywords_faltantes": ["Sin score"]},  # analisis viejo sin score
    ]
    top = perfil_store.top_keywords_faltantes(historial, score_minimo=60)
    keywords = {k["keyword"] for k in top}
    assert keywords == {"Atencion al cliente"}


def test_top_keywords_faltantes_sin_score_minimo_no_filtra():
    historial = [
        {"score_idoneidad": 20, "keywords_faltantes": ["Soldadura"]},
    ]
    top = perfil_store.top_keywords_faltantes(historial)
    assert {k["keyword"] for k in top} == {"Soldadura"}
