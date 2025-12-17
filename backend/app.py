import os
import logging
from typing import Dict, Any, List, Optional
from io import BytesIO
from datetime import datetime

import pandas as pd
import spacy
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

from .config import (
    MENTIONS_REFRESH_SECONDS,
    OFAC_REFRESH_HOURS,
    API_RESULTS_LIMIT,
    SPACY_MODEL,
)
from .ofac import fetch_and_parse_sdn
from .ingest import collect_mentions
from .nlp_utils import build_ofac_name_index, fuzzy_match, fuzzy_top_matches, dedupe_by_core


# ==================================================
# Logging básico
# ==================================================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ofac-monitor")

# ==================================================
# Estado en memoria (simple)
# ==================================================
STATE: Dict[str, Any] = {
    "ofac_entries": [],
    "ofac_meta": {},
    "ofac_index": {"names": [], "map": {}},
    "mentions": [],           # lista de items ya procesados
    "seen_ids": set(),        # dedupe por id
    "last_mentions_run_utc": None,
    "last_error": None,
}

# Mantener referencia global del scheduler (CRÍTICO en Windows)
SCHEDULER: Optional[BackgroundScheduler] = None

# ==================================================
# NLP
# ==================================================
nlp = spacy.load(SPACY_MODEL)

def extract_persons(text: str) -> List[str]:
    doc = nlp(text or "")
    persons = [ent.text.strip() for ent in doc.ents if ent.label_ == "PERSON"]

    # dedupe simple preservando orden
    seen = set()
    out: List[str] = []
    for p in persons:
        k = p.lower()
        if k not in seen and len(p) >= 3:
            out.append(p)
            seen.add(k)
    return out


# ==================================================
# Helpers (Excel)
# ==================================================
def _clip_excel(x: Any, max_len: int = 32767) -> str:
    """
    Excel tiene límite por celda ~32767 chars.
    Además evitamos None y normalizamos saltos de línea.
    """
    s = "—" if x is None else str(x)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if len(s) > max_len:
        s = s[:max_len]
    return s


# ==================================================
# Jobs
# ==================================================
def refresh_ofac():
    try:
        entries, meta = fetch_and_parse_sdn()
        STATE["ofac_entries"] = entries
        STATE["ofac_meta"] = meta
        STATE["ofac_index"] = build_ofac_name_index(entries)
        STATE["last_error"] = None
        log.info("OFAC SDN cargada: %s entradas", meta.get("entries"))
    except Exception as e:
        STATE["last_error"] = f"OFAC refresh error: {e}"
        log.exception("Error refrescando OFAC")

def refresh_mentions():
    import datetime as dt

    try:
        raw = collect_mentions()
        now = dt.datetime.utcnow().isoformat() + "Z"
        out = []

        for item in raw:
            if item["id"] in STATE["seen_ids"]:
                continue

            persons = extract_persons(item["text"])
            matches = []

            # Si OFAC todavía no cargó, igual guardamos el candidato por contexto
            for p in persons:
                m = fuzzy_match(p, STATE["ofac_index"], min_score=92)
                if m:
                    best_name, score, entry = m
                    matches.append(
                        {
                            "candidate": p,
                            "ofac_name": best_name,
                            "score": score,
                            "uid": entry.get("uid"),
                            "type": entry.get("type"),
                        }
                    )

            out.append(
                {
                    **item,
                    "persons": persons,
                    "ofac_matches": matches,
                    "has_ofac_match": bool(matches),
                    "processed_utc": now,
                }
            )
            STATE["seen_ids"].add(item["id"])

        # agregar y capar
        if out:
            STATE["mentions"] = (out + STATE["mentions"])[:API_RESULTS_LIMIT]

        STATE["last_mentions_run_utc"] = now
        STATE["last_error"] = None
        log.info("Menciones procesadas: +%s | total=%s", len(out), len(STATE["mentions"]))
    except Exception as e:
        STATE["last_error"] = f"Mentions refresh error: {e}"
        log.exception("Error refrescando menciones")

def start_scheduler():
    import datetime as dt
    global SCHEDULER

    if SCHEDULER is not None and getattr(SCHEDULER, "running", False):
        return

    SCHEDULER = BackgroundScheduler(daemon=True)

    SCHEDULER.add_job(
        refresh_ofac,
        "interval",
        hours=OFAC_REFRESH_HOURS,
        next_run_time=dt.datetime.utcnow(),
        id="refresh_ofac",
        replace_existing=True,
    )

    SCHEDULER.add_job(
        refresh_mentions,
        "interval",
        seconds=MENTIONS_REFRESH_SECONDS,
        next_run_time=dt.datetime.utcnow(),
        id="refresh_mentions",
        replace_existing=True,
    )

    SCHEDULER.start()
    log.info("Scheduler iniciado (mentions=%ss | ofac=%sh)", MENTIONS_REFRESH_SECONDS, OFAC_REFRESH_HOURS)


# ==================================================
# FastAPI
# ==================================================
app = FastAPI(title="OFAC Social Media Monitor")

static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.on_event("startup")
def on_startup():
    # Corrida inicial inmediata (para que /api/status no salga vacío)
    refresh_ofac()
    refresh_mentions()
    start_scheduler()

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(static_dir, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/status")
def api_status():
    return {
        "ofac_meta": STATE.get("ofac_meta", {}),
        "last_mentions_run_utc": STATE.get("last_mentions_run_utc"),
        "count": len(STATE.get("mentions", [])),
        "mentions_refresh_seconds": MENTIONS_REFRESH_SECONDS,
        "ofac_refresh_hours": OFAC_REFRESH_HOURS,
        "last_error": STATE.get("last_error"),
    }

@app.get("/api/results")
def api_results(only_ofac: int = 0, limit: int = 200):
    limit = max(1, min(int(limit), API_RESULTS_LIMIT))
    items = STATE.get("mentions", [])
    if only_ofac:
        items = [x for x in items if x.get("has_ofac_match")]
    return {"items": items[:limit]}

@app.get("/api/export_excel")
def api_export_excel(only_ofac: int = 0, limit: int = 2000):
    """
    Descarga la info mostrada en /api/results en un .xlsx.
    - only_ofac: 1 filtra solo registros con has_ofac_match
    - limit: cantidad máxima a exportar (capado por API_RESULTS_LIMIT)
    """
    limit = max(1, min(int(limit), API_RESULTS_LIMIT))
    items = STATE.get("mentions", [])
    if only_ofac:
        items = [x for x in items if x.get("has_ofac_match")]
    items = items[:limit]

    # Armado de filas
    rows: List[Dict[str, Any]] = []
    for it in items:
        persons = it.get("persons") or []
        matches = it.get("ofac_matches") or []

        rows.append({
            "processed_utc": _clip_excel(it.get("processed_utc") or it.get("ts_utc")),
            "source": _clip_excel(it.get("source")),
            "published": _clip_excel(it.get("published")),
            "link": _clip_excel(it.get("link")),
            "has_ofac_match": "SI" if it.get("has_ofac_match") else "NO",
            "persons": _clip_excel(" | ".join(persons) if persons else "—"),
            "ofac_matches": _clip_excel(
                " || ".join([
                    f"{m.get('candidate')} -> {m.get('ofac_name')} "
                    f"(score {m.get('score')}{', uid '+str(m.get('uid')) if m.get('uid') else ''})"
                    for m in matches
                ]) if matches else "—"
            ),
            "text": _clip_excel(it.get("text")),
        })

    # DataFrame con validación dura: sin nulos (sin celdas en blanco)
    df = pd.DataFrame(rows, columns=[
        "processed_utc",
        "source",
        "published",
        "link",
        "has_ofac_match",
        "persons",
        "ofac_matches",
        "text",
    ]).fillna("—")

    # Escribir Excel en memoria
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="results")
    bio.seek(0)

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"ofac_social_monitor_{'only_ofac_' if only_ofac else ''}{stamp}.xlsx"

    headers = {
        "Content-Disposition": f'attachment; filename="{fname}"'
    }

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )

@app.get("/api/search_ofac")
def api_search_ofac(q: str, limit: int = 20):
    limit = max(1, min(int(limit), 50))
    q = (q or "").strip()
    if not q:
        return {"items": []}

    ofac_index = STATE.get("ofac_index") or {}
    if not ofac_index.get("names"):
        return {"items": []}

    # 1) obtener candidatos con filtro duro por tokens + scoring compuesto
    matches = fuzzy_top_matches(q, ofac_index, top_k=limit * 3, min_score=80)

    # 2) “nombres únicos” visualmente (colapsa variaciones similares)
    matches = dedupe_by_core(matches, top_k=limit)

    out = []
    for name, score, entry in matches:
        out.append(
            {
                "ofac_name": name,
                "score": score,
                "uid": (entry or {}).get("uid"),
                "type": (entry or {}).get("type"),
            }
        )

    return {"items": out}
