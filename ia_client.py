"""
ia_client.py
------------
Cliente unificado con cascada Gemini -> Groq.

- Gemini (Gemini 2.5 Flash) primario: respuestas creativas y largas, vision.
- Groq (Llama 3.3 70B) secundario: rapido y barato; entra si Gemini falla
  o esta rate-limited.

Las API keys se cargan desde el .env del servidor. El usuario las configura
desde la extension (POST /configurar_keys reescribe el .env y luego llama a
reload_clients()). Sin keys, IAClient devuelve el fallback de cada llamada.

Reglas:
- Cooldowns automaticos parseando "try again in Xh Ym Zs" de los errores.
- TPD (Groq tokens per day) marca Groq sin cuota toda la sesion.
- Cualquier rate limit / 429 / quota dispara cooldown corto y se baja al
  siguiente proveedor.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=True)

log = logging.getLogger("ia")

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash"


def _leer_keys_env() -> tuple[str, str]:
    """Re-lee las keys del proceso (despues de recargar el .env)."""
    return (
        os.getenv("GEMINI_API_KEY", "").strip(),
        os.getenv("GROQ_API_KEY", "").strip(),
    )


class IAClient:
    """Cliente unificado: Gemini -> Groq con fallback automatico."""

    def __init__(self):
        # Gemini
        self._gemini = None
        self._gemini_sin_cuota = False
        self._gemini_cooldown_until = 0.0

        # Groq
        self._groq = None
        self._groq_sin_cuota = False
        self._groq_cooldown_until = 0.0

        self._init_clientes()

    # ── INIT ───────────────────────────────────────────────────────
    def _init_clientes(self) -> None:
        gemini_key, groq_key = _leer_keys_env()
        self._init_gemini(gemini_key)
        self._init_groq(groq_key)

        if not self._gemini and not self._groq:
            log.warning(
                "  [IA] Sin clientes activos. Configura tus API keys desde la extension."
            )

    def _init_gemini(self, key: str) -> None:
        self._gemini = None
        if not key:
            return
        try:
            from google import genai

            self._gemini = genai.Client(api_key=key)
            log.info(f"  [IA] Gemini inicializado ({GEMINI_MODEL}).")
        except Exception as e:
            log.warning(f"  [IA] No se pudo inicializar Gemini: {e}")

    def _init_groq(self, key: str) -> None:
        self._groq = None
        if not key:
            return
        try:
            from groq import Groq

            self._groq = Groq(api_key=key)
            log.info(f"  [IA] Groq inicializado ({GROQ_MODEL}).")
        except Exception as e:
            log.warning(f"  [IA] No se pudo inicializar Groq: {e}")

    def reload(self) -> dict:
        """Re-lee el .env y reinicializa ambos clientes. Devuelve estado."""
        load_dotenv(override=True)
        # Reset de estados al recargar (nuevas keys = nueva cuota presunta)
        self._gemini_sin_cuota = False
        self._gemini_cooldown_until = 0.0
        self._groq_sin_cuota = False
        self._groq_cooldown_until = 0.0
        self._init_clientes()
        return self.estado()

    def estado(self) -> dict:
        gk, qk = _leer_keys_env()
        return {
            "gemini_configurado": bool(gk),
            "groq_configurado": bool(qk),
            "gemini_activo": self._gemini is not None,
            "groq_activo": self._groq is not None,
            "alguno_disponible": self._gemini_disponible() or self._groq_disponible(),
        }

    # ── ESTADO ─────────────────────────────────────────────────────
    def _gemini_disponible(self) -> bool:
        if not self._gemini:
            return False
        if self._gemini_sin_cuota:
            return False
        if time.time() < self._gemini_cooldown_until:
            return False
        return True

    def _groq_disponible(self) -> bool:
        if not self._groq:
            return False
        if self._groq_sin_cuota:
            return False
        if time.time() < self._groq_cooldown_until:
            return False
        return True

    @staticmethod
    def _parse_retry_seconds(error_msg: str) -> float:
        m = re.search(
            r"try again in\s+(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?",
            error_msg,
            re.IGNORECASE,
        )
        if m and any(m.groups()):
            h = int(m.group(1) or 0)
            mn = int(m.group(2) or 0)
            s = float(m.group(3) or 0)
            total = h * 3600 + mn * 60 + s
            if total > 0:
                return total
        return 60.0

    def _marcar_gemini_error(self, e: Exception) -> None:
        msg = str(e)
        msg_low = msg.lower()
        if "quota" in msg_low or "resource exhausted" in msg_low or "429" in msg:
            cooldown = self._parse_retry_seconds(msg)
            self._gemini_cooldown_until = time.time() + cooldown
            log.warning(f"  [IA] Gemini rate-limited / sin cuota, cooldown {cooldown:.0f}s.")
            return
        if "api key" in msg_low or "permission" in msg_low or "unauthenticated" in msg_low:
            self._gemini = None
            log.warning("  [IA] Gemini key invalida. Cliente desactivado.")
            return
        log.warning(f"  [IA] Gemini error: {msg[:140]}")

    def _marcar_groq_error(self, e: Exception) -> None:
        msg = str(e)
        msg_low = msg.lower()
        if "tokens per day" in msg_low or "tpd" in msg_low:
            self._groq_sin_cuota = True
            log.warning("  [IA] Groq sin cuota diaria (TPD). Pausado hasta reset.")
            return
        if "rate_limit" in msg_low or "rate limit" in msg_low or "429" in msg:
            cooldown = self._parse_retry_seconds(msg)
            self._groq_cooldown_until = time.time() + cooldown
            log.warning(f"  [IA] Groq rate-limited, cooldown {cooldown:.0f}s.")
            return
        if "api key" in msg_low or "invalid_api_key" in msg_low or "unauthorized" in msg_low:
            self._groq = None
            log.warning("  [IA] Groq key invalida. Cliente desactivado.")
            return
        log.warning(f"  [IA] Groq error: {msg[:140]}")

    # ── TEXTO ──────────────────────────────────────────────────────
    def chat(self, prompt: str, fallback: str = "", max_tokens: int = 300) -> str:
        """
        Manda un prompt y devuelve la respuesta. Cascada Gemini -> Groq.
        `max_tokens` solo aplica a Groq (Gemini se controla via prompt).
        """
        # 1. Gemini primario
        if self._gemini_disponible():
            try:
                resp = self._gemini.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                )
                out = (resp.text or "").strip()
                if out:
                    return out
            except Exception as e:
                self._marcar_gemini_error(e)

        # 2. Groq secundario
        if self._groq_disponible():
            try:
                resp = self._groq.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                out = (resp.choices[0].message.content or "").strip()
                if out:
                    return out
            except Exception as e:
                self._marcar_groq_error(e)

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

    # ── VISION (siempre Gemini) ────────────────────────────────────
    def vision_disponible(self) -> bool:
        return bool(self._gemini)

    def vision(
        self,
        prompt: str,
        imagen: Path | bytes,
        fallback: str = "",
    ) -> str:
        if not self._gemini_disponible():
            log.warning("  [IA] Vision pedida pero Gemini no esta disponible.")
            return fallback
        try:
            from google.genai import types

            img_bytes = imagen.read_bytes() if isinstance(imagen, Path) else imagen
            resp = self._gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                    prompt,
                ],
            )
            return (resp.text or "").strip()
        except Exception as e:
            self._marcar_gemini_error(e)
            return fallback


# Singleton
_instance: Optional[IAClient] = None


def get_ia() -> IAClient:
    global _instance
    if _instance is None:
        _instance = IAClient()
    return _instance


def reload_ia() -> dict:
    """Para uso del endpoint /configurar_keys: relee .env y rearma clientes."""
    return get_ia().reload()
