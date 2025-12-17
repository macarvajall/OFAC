import io
import zipfile
import requests
import datetime as dt
from xml.etree import ElementTree as ET

from .config import OFAC_SDN_XML_ZIP_URL, OFAC_SDN_XML_URL

def _strip_ns(tag: str) -> str:
    # Maneja namespaces variables (OFAC cambió namespaces con SLS)
    return tag.split("}")[-1] if "}" in tag else tag

def _safe_text(elem):
    return (elem.text or "").strip()

def download_sdn_xml_bytes(timeout=60) -> bytes:
    """
    Intenta descargar SDN XML comprimido (sdn_xml.zip); si falla, usa sdn.xml directo.
    """
    # 1) ZIP
    try:
        r = requests.get(OFAC_SDN_XML_ZIP_URL, timeout=timeout)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        # el zip típicamente contiene sdn.xml
        xml_names = [n for n in z.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise RuntimeError("ZIP no contiene XML")
        return z.read(xml_names[0])
    except Exception:
        # 2) Directo
        r = requests.get(OFAC_SDN_XML_URL, timeout=timeout)
        r.raise_for_status()
        return r.content

def parse_sdn_xml(xml_bytes: bytes) -> list[dict]:
    """
    Parse minimal del SDN.XML: devuelve lista de entradas con campos claves:
    uid, name, type (si está), remarks (si está)
    """
    root = ET.fromstring(xml_bytes)

    entries = []
    for child in root.iter():
        if _strip_ns(child.tag) != "sdnEntry":
            continue

        data = {"uid": None, "name": None, "type": None, "remarks": None}

        # uid suele ser atributo o campo <uid>
        if "uid" in child.attrib:
            data["uid"] = child.attrib.get("uid")

        first = last = whole = typ = remarks = None

        for e in list(child):
            t = _strip_ns(e.tag)
            if t == "uid":
                data["uid"] = _safe_text(e)
            elif t in ("lastName", "last"):
                last = _safe_text(e)
            elif t in ("firstName", "first"):
                first = _safe_text(e)
            elif t in ("sdnName", "name"):
                whole = _safe_text(e)
            elif t in ("sdnType", "type"):
                typ = _safe_text(e)
            elif t in ("remarks",):
                remarks = _safe_text(e)

        # Construir name
        if whole:
            name = whole
        else:
            parts = [p for p in [last, first] if p]
            name = ", ".join(parts) if parts else None

        data["name"] = name
        data["type"] = typ
        data["remarks"] = remarks

        if data["name"]:
            entries.append(data)

    # fallback si el iter anterior no encontró: algunos SDN XML vienen con estructura distinta
    if not entries:
        for sdnEntry in root.findall(".//"):
            if _strip_ns(sdnEntry.tag) != "sdnEntry":
                continue
            name = None
            uid = sdnEntry.attrib.get("uid")
            # intenta sdnName en cualquier profundidad
            for e in sdnEntry.iter():
                if _strip_ns(e.tag) in ("sdnName", "name"):
                    name = _safe_text(e)
                    break
            if name:
                entries.append({"uid": uid, "name": name, "type": None, "remarks": None})

    return entries

def fetch_and_parse_sdn() -> tuple[list[dict], dict]:
    """
    Retorna (entries, meta) con timestamps.
    """
    started = dt.datetime.utcnow()
    xml_bytes = download_sdn_xml_bytes()
    entries = parse_sdn_xml(xml_bytes)
    meta = {
        "fetched_at_utc": started.isoformat() + "Z",
        "entries": len(entries),
        "source_zip": OFAC_SDN_XML_ZIP_URL,
        "source_xml": OFAC_SDN_XML_URL,
    }
    return entries, meta
