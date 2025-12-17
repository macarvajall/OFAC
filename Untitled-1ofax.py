"""
OFAC SOCIAL MEDIA MONITOR
--------------------------------------------------
Genera un listado de personas mencionadas en redes sociales y medios
en contextos de sanciones OFAC, corrupción, LA/FT, terrorismo, etc.

Requiere:
    pip install pandas spacy snscrape beautifulsoup4 requests
    python -m spacy download en_core_web_sm
--------------------------------------------------
"""

import os
import re
import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import spacy

# ==============================================================
# CONFIGURACIÓN
# ==============================================================

OUTPUT_FILE = "ofac_social_candidates.csv"
MAX_TWEETS_PER_SOURCE = 200

# Fuentes oficiales y medios confiables (sin @)
TWITTER_SOURCES = [
    "USTreasury", "USTreasuryPres", "TheJusticeDept", "OCCRP", "UN", "UNODC",
    "Reuters", "AP", "Bloomberg", "FinancialTimes", "WSJ", "el_pais",
    "FiscaliaCol", "PoliciaColombia", "UIAFColombia", "infopresidencia",
    "TransparencyOrg"
]

# Palabras clave relevantes
KEYWORDS = [
    "ofac", "sdn list", "sanctions", "designated", "Specially Designated Nationals",
    "lista clinton", "lista negra", "money laundering", "terrorism financing",
    "drug trafficking", "corrupción", "lavado", "financiación del terrorismo",
    "investigado", "acusado", "sancionado", "proposed sanctions", "blacklist"
]

# Feeds de medios (opcional)
NEWS_FEEDS = [
    "https://www.reuters.com/rssFeed/worldNews",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada"
]

# Inicializar modelo NLP
print("Cargando modelo spaCy...")
nlp = spacy.load("en_core_web_sm")


# ==============================================================
# FUNCIONES
# ==============================================================

def text_matches_keywords(text):
    """Evalúa si el texto contiene palabras clave relevantes."""
    txt = text.lower()
    return any(kw in txt for kw in KEYWORDS)


def extract_persons(text):
    """Extrae entidades PERSON usando spaCy."""
    doc = nlp(text)
    persons = [ent.text.strip() for ent in doc.ents if ent.label_ == "PERSON"]
    return list(set(persons))


def fetch_tweets_from_user(username, max_count=100):
    """Obtiene tweets recientes de una cuenta usando snscrape."""
    import snscrape.modules.twitter as sntwitter
    tweets = []
    try:
        for i, tweet in enumerate(sntwitter.TwitterUserScraper(username).get_items()):
            if i >= max_count:
                break
            tweets.append(tweet.content)
    except Exception as e:
        print(f"[!] Error obteniendo tweets de @{username}: {e}")
    return tweets


def fetch_rss_articles(feed_url):
    """Descarga artículos desde un feed RSS."""
    try:
        resp = requests.get(feed_url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
        return [item.title.text + " " + item.description.text for item in items]
    except Exception as e:
        print(f"[!] Error leyendo feed {feed_url}: {e}")
        return []


# ==============================================================
# PIPELINE PRINCIPAL
# ==============================================================

def main():
    print("=== Iniciando monitoreo OFAC social media ===")
    resultados = []

    # ---- 1. Redes sociales ----
    for user in TWITTER_SOURCES:
        print(f"Descargando tweets de @{user}...")
        tweets = fetch_tweets_from_user(user, MAX_TWEETS_PER_SOURCE)
        for tw in tweets:
            if text_matches_keywords(tw):
                persons = extract_persons(tw)
                if persons:
                    resultados.append({
                        "nombre": "; ".join(persons),
                        "fuente": f"Twitter @{user}",
                        "texto": tw[:280],
                        "tipo": "twitter",
                        "fecha": datetime.utcnow().isoformat()
                    })

    # ---- 2. Noticias RSS ----
    print("Descargando artículos de medios...")
    for feed in NEWS_FEEDS:
        articles = fetch_rss_articles(feed)
        for art in articles:
            if text_matches_keywords(art):
                persons = extract_persons(art)
                if persons:
                    resultados.append({
                        "nombre": "; ".join(persons),
                        "fuente": feed,
                        "texto": art[:300],
                        "tipo": "news",
                        "fecha": datetime.utcnow().isoformat()
                    })

    # ---- 3. Consolidar resultados ----
    if not resultados:
        print("No se encontraron resultados relevantes.")
        return

    df = pd.DataFrame(resultados)
    df["nombre_normalizado"] = df["nombre"].apply(lambda x: re.sub(r"[^A-Za-zÁÉÍÓÚáéíóúñÑ ]", "", x).strip().upper())
    df.drop_duplicates(subset=["nombre_normalizado", "texto"], inplace=True)

    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n✅ Archivo exportado: {OUTPUT_FILE}")
    print(f"Total registros: {len(df)}")
    print("Ejemplo:")
    print(df.head(10))


# ==============================================================
# MAIN
# ==============================================================

if __name__ == "__main__":
    main()
