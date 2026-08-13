"""
ia_client.py
-----------
Cliente dual: DeepSeek para texto + Gemini para vision.

- DeepSeek (deepseek-v4-flash) via API compatible OpenAI para chat/analisis.
- Gemini via google-genai SDK exclusivamente para vision.
- Las API keys se cargan desde el .env del servidor.
- Sin keys, IAClient devuelve el fallback de cada llamada.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=True)

log = logging.getLogger("ia")

DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
GEMINI_MODEL = "gemini-2.5-flash"


def _leer_key_env(clave: str = "DEEPSEEK_API_KEY") -> str:
    return os.getenv(clave, "").strip()


class IAClient:
    """Cliente dual: DeepSeek para texto, Gemini para vision."""

    def __init__(self):
        self._client = None
        self._sin_cuota = False
        self._cooldown_until = 0.0
        self._gemini_client = None
        self._init_cliente()

    # ── INIT ───────────────────────────────────────────────────────
    def _init_cliente(self) -> None:
        dk = _leer_key_env("DEEPSEEK_API_KEY")
        gk = _leer_key_env("GEMINI_API_KEY")
        self._init_deepseek(dk)
        self._init_gemini(gk)
        if not self._client and not self._gemini_client:
            log.warning("  [IA] Sin cliente activo. Configura API keys desde la extension.")

    def _init_deepseek(self, key: str) -> None:
        self._client = None
        if not key:
            return
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL)
            log.info(f"  [IA] DeepSeek inicializado ({DEEPSEEK_MODEL}).")
        except Exception as e:
            log.warning(f"  [IA] No se pudo inicializar DeepSeek: {e}")

    def _init_gemini(self, key: str) -> None:
        self._gemini_client = None
        if not key:
            return
        try:
            from google import genai

            self._gemini_client = genai.Client(api_key=key)
            log.info(f"  [IA] Gemini inicializado ({GEMINI_MODEL}) solo para vision.")
        except Exception as e:
            log.warning(f"  [IA] No se pudo inicializar Gemini: {e}")

    def reload(self) -> dict:
        """Re-lee el .env y reinicializa los clientes. Devuelve estado."""
        load_dotenv(override=True)
        self._sin_cuota = False
        self._cooldown_until = 0.0
        self._init_cliente()
        return self.estado()

    def estado(self) -> dict:
        dk = _leer_key_env("DEEPSEEK_API_KEY")
        gk = _leer_key_env("GEMINI_API_KEY")
        return {
            "deepseek_configurado": bool(dk),
            "deepseek_activo": self._client is not None,
            "gemini_configurado": bool(gk),
            "gemini_activo": self._gemini_client is not None,
            "alguno_disponible": self._disponible() or self._gemini_disponible(),
        }

    # ── ESTADO ─────────────────────────────────────────────────────
    def _disponible(self) -> bool:
        if not self._client:
            return False
        if self._sin_cuota:
            return False
        if time.time() < self._cooldown_until:
            return False
        return True

    def _gemini_disponible(self) -> bool:
        return self._gemini_client is not None

    def _marcar_error(self, e: Exception, es_vision: bool = False) -> None:
        msg = str(e)
        msg_low = msg.lower()
        if "rate" in msg_low or "429" in msg or "too many requests" in msg_low:
            self._cooldown_until = time.time() + 60
            log.warning(f"  [IA] DeepSeek rate-limited, cooldown 60s.")
            return
        if "insufficient_quota" in msg_low or "quota" in msg_low or "exceeded" in msg_low:
            self._sin_cuota = True
            log.warning("  [IA] DeepSeek sin cuota. Pausado hasta reset de cuenta.")
            return
        if es_vision:
            log.warning(f"  [IA] DeepSeek vision fallo (no soportado): {msg[:100]}")
            return
        if "api key" in msg_low or "invalid" in msg_low or "unauthorized" in msg_low or "authentication" in msg_low:
            self._client = None
            log.warning("  [IA] DeepSeek key invalida. Cliente desactivado.")
            return
        log.warning(f"  [IA] DeepSeek error: {msg[:140]}")

    # ── TEXTO ──────────────────────────────────────────────────────
    def chat(self, prompt: str, fallback: str = "", max_tokens: int = 300, pensar: bool = False) -> str:
        """pensar=True habilita el "thinking" extendido de DeepSeek. Por
        defecto va apagado (respuestas rapidas para el relleno de formularios
        en vivo); activalo en llamadas puntuales y mas importantes donde vale
        la pena que el modelo razone antes de responder (ej. componer el CV)."""
        if self._disponible():
            try:
                resp = self._client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    extra_body={"thinking": {"type": "enabled" if pensar else "disabled"}},
                )
                out = (resp.choices[0].message.content or "").strip()
                if out:
                    return out
            except Exception as e:
                self._marcar_error(e)

        log.warning(f"  [IA] Sin IA disponible, usando fallback: '{fallback[:40]}'")
        return fallback

    # ── SI/NO ──────────────────────────────────────────────────────
    def si_no(self, pregunta: str, default: bool = True) -> bool:
        prompt = f"Responde SOLO con SI o NO a esta pregunta:\n{pregunta}"
        resp = self.chat(prompt, fallback="SI" if default else "NO", max_tokens=10)
        return resp.strip().upper().startswith("SI")

    # ── ELEGIR ─────────────────────────────────────────────────────
    def elegir(self, pregunta: str, opciones: list[str], contexto: str = "") -> str:
        if not opciones:
            return ""
        opts_str = "\n".join(f"- {o}" for o in opciones)
        prompt = (
            f"{contexto}\n\n"
            f"Pregunta: {pregunta}\n"
            f"Opciones disponibles:\n{opts_str}\n\n"
            "Responde SOLO con el texto exacto de la opcion mas adecuada."
        )
        resp = self.chat(prompt, fallback=opciones[0], max_tokens=80).strip().lower()
        for opt in opciones:
            if resp == opt.lower() or resp in opt.lower() or opt.lower() in resp:
                return opt
        return opciones[0]

    # ── VISION (Gemini) ────────────────────────────────────────────
    def vision_disponible(self) -> bool:
        return self._gemini_disponible()

    def _gemini_vision(self, prompt: str, imagen_bytes: bytes) -> str:
        import PIL.Image
        import io
        img = PIL.Image.open(io.BytesIO(imagen_bytes))
        resp = self._gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, img],
        )
        return (resp.text or "").strip()

    def vision(
        self,
        prompt: str,
        imagen: Path | bytes,
        fallback: str = "",
    ) -> str:
        if not self._gemini_disponible():
            log.warning("  [IA] Vision no disponible (Gemini no configurado). Usando fallback.")
            return fallback
        try:
            if isinstance(imagen, Path):
                imagen_bytes = imagen.read_bytes()
            else:
                imagen_bytes = imagen
            return self._gemini_vision(prompt, imagen_bytes)
        except Exception as e:
            log.warning(f"  [IA] Gemini vision fallo: {e}")
            return fallback


# Singleton
_instance: Optional[IAClient] = None


def get_ia() -> IAClient:
    global _instance
    if _instance is None:
        _instance = IAClient()
    return _instance


def reload_ia() -> dict:
    """Para uso del endpoint /configurar_keys: relee .env y rearma cliente."""
    return get_ia().reload()
