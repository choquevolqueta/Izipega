# Izipega — agent guidance

## Identity
Chrome MV3 extension + local FastAPI server that analyzes job offers and auto-fills web forms using DeepSeek (OpenAI-compatible API).

## Architecture
- `server.py` — thin FastAPI layer on `localhost:8765`. Endpoints: `/ping`, `/analizar`, `/rellenar`, `/proponer_perfil`, `/aplicar_perfil`, `/generar_cv`, `/generar_cv_pdf`, `/configurar_keys`, `/limpiar_contexto`, `/historial_keywords`. Routes only — delegates to the modules below.
- `models.py` — Pydantic request/response models.
- `perfil_store.py` — profile/context/history state + persistence. Mutable state (`PERFIL`, `_CONTEXTO`) lives here behind `get_perfil()`/`get_contexto()`/`set_contexto()` accessors; other modules must call these (not import a bare name) to avoid stale references after a reload.
- `ia_logic.py` — prompt building + AI calls: `respuesta_directa` (free, no tokens), `respuesta_ia_para_pregunta`, `analizar_contexto_logic`, `proponer_perfil_desde_texto`, `optimizar_cv_con_ia`, `rellenar_campo` (dispatches by field type).
- `cv_export.py` — `ordenar_experiencia_reciente`, `_vinetas_de`, `construir_cv_pdf` (fpdf2 render, no AI calls).
- `ia_client.py` — DeepSeek via `openai` library (`base_url=https://api.deepseek.com`). Model `deepseek-v4-flash` for text. Gemini (`google-genai`) used exclusively for vision — DeepSeek's chat API has no vision support, Gemini fills that gap.
- `extension/` — Chrome side panel (MV3, `side_panel` API, all_frames content script)
- `tests/` — pytest, covers the pure logic in `perfil_store.py`/`ia_logic.py`/`cv_export.py` without needing API keys. CI in `.github/workflows/tests.yml`.

## Running
- **Always** use `lanzar_servidor.bat` (not direct `python server.py`). It verifies Python, creates venv, installs deps, copies `perfil.json.template → perfil.json`, and creates desktop shortcut.
- Server runs from `.venv` via `venv\Scripts\python.exe server.py`.
- Extension is "Load unpacked" → `extension/` folder.

## Key data files (all gitignored except template)
- `perfil.json` — user profile (JSON, from template or uploaded CV)
- `perfil.json.template` — committed schema reference (editable)
- `.env` — `DEEPSEEK_API_KEY`
- `contexto_actual.json` — last job analysis (resets on each `/analizar`)
- `historial_keywords.json` — ring buffer (max 10 entries) of past analyses
- `perfil_propuesto.json` — pending profile proposal extracted from an uploaded PDF, awaiting user approval
- `perfil_backups/` — auto-backups before applying new profile

## Profile schema
Profile has `experiencia` (array with `cargo`/`empresa`/`periodo`/`descripcion` or `vinetas`), `estudios`, `habilidades`, `herramientas`, `idiomas` (objects `{idioma, nivel}`), `redes` (`linkedin`/`portafolio_web`/`behance`), `respuestas_extra` (freeform key-value for FAQ fields).

## Important quirks
- **Context resets per analysis**: `/analizar` always deletes previous context first. User must re-analyze each job listing.
- **Direct answers** (no token cost) for: phone, email, city, comuna, salary, availability, LinkedIn, portfolio, nationality, driving license, legal residence. Contact combo fields get priority before individual matches.
- **Experience ordering**: chronological by recency (not relevance). "Present/actual" gets year 9999.
- **CV PDF**: generated serverside via `fpdf2`. Uses Arial from `C:\Windows\Fonts`; falls back to Helvetica (sanes to latin-1) if missing.
- **Content script guard**: uses `window.__escritor_magico_loaded` flag to prevent double initialization.
- **Vision**: only sent to DeepSeek. If DeepSeek is unavailable, vision request falls back to text-only.

## Keyboard shortcuts (configurable at chrome://extensions/shortcuts)
- `Alt+Shift+E` — toggle side panel
- `Alt+A` — analyze context
- `Alt+R` — fill form
- `Alt+Q` — force refill

## Language
All user-facing text is in Spanish. Prompts to AI are in Spanish. Variables mix Spanish and English.
