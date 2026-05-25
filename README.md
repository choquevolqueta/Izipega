
# Izipega

Extensión de Chrome + servidor local que rellena cualquier formulario web usando tu perfil y un par de modelos de IA gratuitos (Gemini como primario, Groq como respaldo).

> ⚠️ **Versión demo / beta en evaluación.** Funciona, pero esperá bugs. Reportá lo que encuentres como issue.

<img width="1201" height="532" alt="iziejemplo" src="https://github.com/user-attachments/assets/1b986bc3-ee4b-4ef5-a458-34b2cb8b9cc8" />

## Qué necesitás antes de empezar

- **Chrome** (o navegador basado en Chromium)
- **Python 3.10+** ([cómo instalarlo](#instalar-python-3-minutos))
- Una API key gratis de al menos uno (te las pide la extensión al abrirla la primera vez):
  - **Gemini** (recomendado, más generoso): https://aistudio.google.com/apikey
  - **Groq** (respaldo): https://console.groq.com/keys

---

### Instalar Python (3 minutos)

Si ya tenés Python instalado, saltá esto.

1. Andá a 👉 **https://www.python.org/downloads/**
2. Click en el botón amarillo grande **"Download Python 3.X.X"**.
3. Abrí el instalador descargado.
4. 🔴 **CRÍTICO:** en la **primera pantalla** del instalador, antes de tocar "Install Now", **marcá la casilla**:

   > ☑ **Add Python to PATH** ← está abajo, fácil de pasar por alto

   Sin esa casilla marcada, Izipega no va a poder arrancar.

5. Click "Install Now". Esperá ~2 minutos. Cerrá el instalador.
6. Listo. Andá al siguiente paso.

---

## Arranque (primera vez)

1. **Doble click en `lanzar_servidor.bat`**. La primera vez:
   - Verifica que Python esté instalado (si no, te dice qué hacer).
   - Crea un `venv` e instala las dependencias automáticamente.
   - Copia `perfil.json.template` → `perfil.json` (tu archivo de datos personales, **local, no se sube a ningún lado**).
   - Crea un acceso directo `Izipega.lnk` en tu escritorio para próximas veces.
2. En Chrome andá a `chrome://extensions`, activá "Modo desarrollador" (arriba a la derecha) y pulsá **"Cargar descomprimida"**. Elegí la carpeta `extension/`.
3. Pin la extensión (icono de pin en la barra de extensiones). Al hacer click en el icono se abre el panel lateral.
4. La primera vez te va a pedir pegar tus API keys. Pegá al menos una y dale "Guardar y conectar". Quedan guardadas en `.env` (en tu PC, no se mandan a ningún lado).
5. Subí tu CV en PDF desde la zona "Actualizar perfil con un CV" para llenar tu perfil. Revisá la propuesta y aceptá.

**Próximas veces:** doble click al acceso directo `Izipega.lnk` del escritorio. Listo en 2 segundos.

## Cómo usarla

- **Analizar contexto** (opcional pero recomendado): en una página de oferta laboral, analiza el texto y calcula un score de idoneidad 0-100 + extrae las keywords ATS (habilidades duras/blandas, experiencia requerida).
- **Rellenar formulario**: detecta los campos vacíos del formulario y los completa con tu perfil + IA. Usa visión por campo (más lento pero más preciso, no inventa datos que no estén en tu perfil).
- **Re-llenar (forzar)**: limpia y vuelve a llenar, ignorando los atajos directos del perfil.

### Atajos de teclado

| Acción | Atajo |
|---|---|
| Abrir / cerrar panel lateral | `Alt+Shift+E` |
| Analizar contexto | `Alt+A` |
| Rellenar formulario | `Alt+R` |
| Re-llenar (forzar) | `Alt+G` |

Editables en `chrome://extensions/shortcuts`.

## Editar tu perfil

- **Subiendo un CV nuevo**: arrastrá un PDF al panel. La IA propone un perfil, vos revisás y aceptás. Se hace backup automático.
- **Manualmente**: click en "Editar manualmente" en el panel. Editor amigable para datos personales, habilidades, redes y respuestas a preguntas frecuentes (formato Q&A).
- **Experiencia y estudios** solo se actualizan subiendo un CV (intencionalmente — evita romper la estructura).

## Reconfigurar API keys

Click en el icono ⚙ del panel lateral. Podés cambiar una o ambas keys cuando quieras.

## Estructura del proyecto

```
izipega/
├── server.py              FastAPI en localhost:8765
├── ia_client.py           Cascada Gemini → Groq
├── perfil.json.template   Plantilla del schema de perfil (se commitea)
├── perfil.json            Tu perfil personal (gitignored, se crea solo)
├── requirements.txt
├── lanzar_servidor.bat
├── LICENSE                MIT
├── .env                   Tus API keys (gitignored, se crea solo)
├── .env.example
└── extension/             Carga descomprimida en chrome://extensions
```

## Privacidad

- **Todo corre en tu máquina.** El servidor escucha solo en `127.0.0.1:8765`.
- **Las API keys** se guardan en `.env` local (gitignored).
- **Tu perfil** queda en `perfil.json` local (gitignored).
- **Los únicos datos que salen de tu PC** son los prompts que mandás a Gemini o Groq cuando se activan. No se mandan a ningún otro servicio.

## Solución de problemas

- **"NO PUEDO ENCONTRAR PYTHON" al abrir el .bat**: no tenés Python instalado, o lo instalaste sin marcar "Add to PATH". Mirá la [sección de instalar Python](#instalar-python-3-minutos) y reinstalá con la casilla marcada.
- **"servidor offline" en la extensión**: el `.bat` no está corriendo. Doble click otra vez (o usá el acceso directo `Izipega.lnk` del escritorio).
- **"Las keys guardadas no funcionan"**: la key está mal o caducada. Click en ⚙ y pegá una nueva.
- **El PDF no extrae nada**: probablemente está escaneado (es una imagen). Pasalo por OCR antes.
- **"No detecté campos"**: asegurate de tener un formulario visible en la pestaña activa. Algunos sitios meten los campos en iframes; la extensión los detecta automáticamente pero puede fallar en sitios muy custom.
- **Respuestas raras de la IA**: re-analizá el contexto, o tocá "Re-llenar (forzar)" para que use visión sobre cada campo.

## Limitaciones conocidas

- Solo Chrome / navegadores Chromium (la Side Panel API no existe en Firefox/Safari).
- No funciona si la pestaña está minimizada o no es la activa (Chrome no captura).
- Sitios con anti-bot agresivo (Cloudflare Turnstile, etc.) pueden bloquear los clicks sintéticos al aplicar las respuestas.
- PDF escaneados no se procesan (necesitarían OCR, no implementado).

## Contribuir

Issues y PRs bienvenidos. Esto es código de fin de semana, hay deuda técnica.

## Licencia

[MIT](LICENSE). Hacé lo que quieras, citá si te sirve.
