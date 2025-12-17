import re
import unicodedata
from rapidfuzz import fuzz, process

# =========================
# Normalización dura
# =========================
_ENTITY_STOPWORDS = {
    "COMPANY","CO","CORP","CORPORATION","INC","INCORPORATED","LLC","LTD","LIMITED",
    "S","A","SA","SAS","S.A","S.A.","S A","AG","GMBH","BV","NV","SPA","SRL","SRO",
    "BANK","BANCO","TRUST","HOLDINGS","HOLDING","GROUP","GRUPO","FUND","FOUNDATION"
}

def _strip_accents(s: str) -> str:
    # "PETRÓ" -> "PETRO"
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def normalize_name(s: str) -> str:
    s = (s or "").upper()
    s = _strip_accents(s)
    s = re.sub(r"[^A-ZÑ ]", " ", s)       # solo letras y espacios
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize_name(norm: str) -> list[str]:
    # tokens con longitud >=2 para no meter ruido tipo "A"
    toks = [t for t in (norm or "").split(" ") if len(t) >= 2]
    return toks

def looks_like_entity(tokens: list[str]) -> bool:
    if not tokens:
        return False
    # si contiene palabras típicas de empresa o termina en SA/LLC etc.
    hit = sum(1 for t in tokens if t in _ENTITY_STOPWORDS)
    return hit >= 1

# =========================
# Index OFAC (con bloqueo por tokens)
# =========================
def build_ofac_name_index(ofac_entries: list[dict]) -> dict:
    """
    Estructura:
      - items: lista de dicts con {norm, tokens, is_entity, entry}
      - token_to_ids: token -> set(indices) (para prefiltrar)
      - names: lista de norm (para rapidfuzz, pero ya prefiltrada)
      - map: norm -> entry (primera ocurrencia)
    """
    items = []
    token_to_ids: dict[str, set[int]] = {}
    names = []
    mp = {}

    for e in (ofac_entries or []):
        raw = e.get("name", "") or ""
        norm = normalize_name(raw)
        if not norm:
            continue

        toks = tokenize_name(norm)
        if not toks:
            continue

        is_ent = looks_like_entity(toks)

        idx = len(items)
        items.append({
            "norm": norm,
            "tokens": toks,
            "token_set": set(toks),
            "is_entity": is_ent,
            "entry": e,
        })

        names.append(norm)
        mp.setdefault(norm, e)

        # inverted index por token (bloqueo)
        for t in set(toks):
            if len(t) < 3:
                continue
            token_to_ids.setdefault(t, set()).add(idx)

    return {"items": items, "token_to_ids": token_to_ids, "names": names, "map": mp}

# =========================
# Matching mejorado (únicos / relevantes)
# =========================
def _candidate_ids_for_query(q_tokens: list[str], ofac_index: dict, max_pool: int = 5000) -> list[int]:
    """
    Pre-filtro por tokens:
      - usa intersección/union de postings para reducir el universo
      - si no hay postings, retorna [] (sin candidatos)
    """
    token_to_ids = ofac_index.get("token_to_ids", {}) or {}
    postings = []
    for t in set(q_tokens):
        if len(t) < 3:
            continue
        ids = token_to_ids.get(t)
        if ids:
            postings.append(ids)

    if not postings:
        return []

    # estrategia: arrancar con el token más "raro" (menor posting)
    postings.sort(key=len)
    pool = set(postings[0])

    # si la query tiene 2+ tokens, intenta intersecar para aumentar precisión
    for ids in postings[1:]:
        # intersección suave: si se muere la intersección, deja union (para no perder recall)
        inter = pool.intersection(ids)
        if inter:
            pool = inter
        else:
            pool = pool.union(ids)

        if len(pool) > max_pool:
            break

    # devuelve lista estable
    return list(pool)

def fuzzy_match(name: str, ofac_index: dict, min_score: int = 92):
    """
    Devuelve (best_name, score, entry) o None
    Reglas duras anti-“falsos positivos”:
      - si query tiene >=2 tokens: exige mínimo 2 tokens en común
      - si query tiene exactamente 2 tokens: (por defecto) exige que ambos tokens aparezcan
      - penaliza entidades cuando query parece persona
    """
    q = normalize_name(name)
    if not q:
        return None

    # exacto
    mp = ofac_index.get("map", {}) or {}
    if q in mp:
        return (q, 100, mp[q])

    q_tokens = tokenize_name(q)
    if len(q_tokens) < 2:
        # si solo hay 1 token, es demasiado ambiguo para OFAC
        return None

    q_is_entity = looks_like_entity(q_tokens)

    cand_ids = _candidate_ids_for_query(q_tokens, ofac_index)
    if not cand_ids:
        return None

    items = ofac_index.get("items", []) or []

    # scoring compuesto + reglas duras por intersección
    best = None  # (score, norm, entry)
    q_set = set(q_tokens)

    for cid in cand_ids:
        it = items[cid]
        c_norm = it["norm"]
        c_set = it["token_set"]

        overlap = len(q_set.intersection(c_set))

        # regla dura: mínimo 2 tokens en común
        if overlap < 2:
            continue

        # regla extra: si query son 2 tokens, exigir ambos (evita "PETRO ..." sin "GUSTAVO")
        if len(q_set) == 2 and overlap < 2:
            continue

        # base scorers
        s1 = fuzz.WRatio(q, c_norm)
        s2 = fuzz.token_set_ratio(q, c_norm)

        # jaccard en tokens (0-100)
        j = 100.0 * (overlap / max(1, len(q_set.union(c_set))))

        score = 0.55 * s1 + 0.30 * s2 + 0.15 * j

        # penalización: si query parece persona y candidato es entidad
        if (not q_is_entity) and it["is_entity"]:
            score -= 8.0

        # pequeño bonus si todos los tokens de query están incluidos en el candidato
        if q_set.issubset(c_set):
            score += 3.0

        if best is None or score > best[0]:
            best = (score, c_norm, it["entry"])

    if not best:
        return None

    score, best_name, entry = best
    if score >= float(min_score):
        return (best_name, round(float(score), 1), entry)

    return None

def fuzzy_top_matches(name: str, ofac_index: dict, top_k: int = 10, min_score: int = 80) -> list[tuple[str, float, dict]]:
    """
    Para UI: lista top_k (name_norm, score, entry) con el mismo filtro duro de tokens.
    """
    q = normalize_name(name)
    q_tokens = tokenize_name(q)
    if not q or len(q_tokens) < 2:
        return []

    q_is_entity = looks_like_entity(q_tokens)
    q_set = set(q_tokens)

    cand_ids = _candidate_ids_for_query(q_tokens, ofac_index)
    if not cand_ids:
        return []

    items = ofac_index.get("items", []) or []
    scored = []

    for cid in cand_ids:
        it = items[cid]
        c_norm = it["norm"]
        c_set = it["token_set"]
        overlap = len(q_set.intersection(c_set))
        if overlap < 2:
            continue
        if len(q_set) == 2 and overlap < 2:
            continue

        s1 = fuzz.WRatio(q, c_norm)
        s2 = fuzz.token_set_ratio(q, c_norm)
        j = 100.0 * (overlap / max(1, len(q_set.union(c_set))))

        score = 0.55 * s1 + 0.30 * s2 + 0.15 * j
        if (not q_is_entity) and it["is_entity"]:
            score -= 8.0
        if q_set.issubset(c_set):
            score += 3.0

        if score >= min_score:
            scored.append((c_norm, round(float(score), 1), it["entry"]))

    scored.sort(key=lambda x: (-x[1], x[0]))

    # “únicos” por nombre normalizado (ya lo es), pero además puedes colapsar por core si quieres
    return scored[:max(1, int(top_k))]




def core_person_key(norm_name: str) -> str:
    """
    Key “core” para deduplicar resultados similares en UI.
    Heurística:
      - usa los 2 primeros tokens (OFAC suele venir como "APELLIDO NOMBRE ...")
    """
    toks = tokenize_name(normalize_name(norm_name))
    if len(toks) < 2:
        return norm_name
    return f"{toks[0]}|{toks[1]}"

def dedupe_by_core(matches: list[tuple[str, float, dict]], top_k: int = 10) -> list[tuple[str, float, dict]]:
    """
    Dedup visual: si salen muchas variantes del mismo “core”, deja solo la mejor (primera).
    Asume que matches ya viene ordenado desc por score.
    """
    seen = set()
    out: list[tuple[str, float, dict]] = []
    for nm, sc, e in matches:
        key = core_person_key(nm)
        if key in seen:
            continue
        seen.add(key)
        out.append((nm, sc, e))
        if len(out) >= max(1, int(top_k)):
            break
    return out
