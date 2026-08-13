"""
models.py
---------
Modelos Pydantic compartidos por las rutas de server.py.
"""

from __future__ import annotations

from pydantic import BaseModel


class AnalizarRequest(BaseModel):
    titulo: str = ""
    descripcion: str = ""
    imagen_base64: str = ""


class CampoMeta(BaseModel):
    label: str = ""
    placeholder: str = ""
    name: str = ""
    id: str = ""
    aria_label: str = ""
    aria_describedby_texto: str = ""
    legend: str = ""
    hermanos: str = ""
    tipo_input: str = ""


class Campo(BaseModel):
    id: str
    tipo: str  # text | textarea | radio | checkbox | select
    label: str
    opciones: list[str] | None = None
    meta: CampoMeta | None = None


class RellenarRequest(BaseModel):
    titulo_contexto: str = ""
    campos: list[Campo]
    usar_directas: bool = True
    imagen_base64: str = ""


class Respuesta(BaseModel):
    id: str
    tipo: str
    valor: str


class RellenarResponse(BaseModel):
    respuestas: list[Respuesta]


class ConfigurarKeysRequest(BaseModel):
    deepseek_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""


class AplicarPerfilRequest(BaseModel):
    perfil: dict


class GenerarCVRequest(BaseModel):
    optimizar: bool = True
    perfil: dict | None = None  # borrador a optimizar; si es None usa el perfil guardado
