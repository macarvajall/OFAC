import os

# ==============================
# Intervalos (segundos)
# ==============================
MENTIONS_REFRESH_SECONDS = int(os.getenv("MENTIONS_REFRESH_SECONDS", "180"))   # cada 3 min (ticker)
OFAC_REFRESH_HOURS       = int(os.getenv("OFAC_REFRESH_HOURS", "12"))          # cada 12h (listas)
API_RESULTS_LIMIT        = int(os.getenv("API_RESULTS_LIMIT", "300"))

# ==============================
# OFAC SDN: fuentes oficiales (listas)
# ==============================
OFAC_SDN_XML_ZIP_URL = os.getenv("OFAC_SDN_XML_ZIP_URL", "https://www.treasury.gov/ofac/downloads/sdn_xml.zip")
OFAC_SDN_XML_URL     = os.getenv("OFAC_SDN_XML_URL",     "https://www.treasury.gov/ofac/downloads/sdn.xml")

# ==============================
# NLP
# ==============================
SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_sm")

# ==============================
# RSS / Atom (rápidos, tipo “stream”)
# ==============================
NEWS_FEEDS = [
    # Medios (ya tenías)
    "https://www.reuters.com/rssFeed/worldNews",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada",

    # Gobierno / enforcement
    "https://www.justice.gov/news/rss?m=1",  # DOJ All News (RSS)
    "https://www.fbi.gov/feeds/national-press-releases/rss.xml",  # FBI National PR (RSS2)

    # Sanciones internacionales
    "https://www.un.org/securitycouncil/feed/1.0/updates_unsc_consolidated_list",  # UNSC consolidated list updates
    "https://ofsi.blog.gov.uk/feed/",  # UK OFSI (Atom)
    "https://www.consilium.europa.eu/api/rss?lng=en&cms=consilium&contenttype=PressRelease&title=Press%20releases",  # EU Council PR (RSS endpoint)

    # Canadá (feed por departamento; ajustable)
    "https://api.io.canada.ca/io-server/gc/news/en/v2?department=international_development&sort=publishedDate&order=desc&limit=20",
]

# ==============================
# Páginas HTML (cuando NO hay RSS confiable)
# ==============================
HTML_SOURCES = [
    # OFAC (no hay RSS oficial activo; toca HTML)
    "https://ofac.treasury.gov/recent-actions",
    "https://ofac.treasury.gov/press-releases",

    # Treasury HQ (útil para sanciones/acciones)
    "https://home.treasury.gov/news/press-releases",

    # State (si RSS falla por “technical difficulties”)
    "https://www.state.gov/press-releases",
]

# ==============================
# Metafuentes (para emular “trending / menciones”)
# ==============================
ENABLE_GDELT = os.getenv("ENABLE_GDELT", "1") == "1"
GDELT_DOC_API = os.getenv("GDELT_DOC_API", "https://api.gdeltproject.org/api/v2/doc/doc")

ENABLE_GOOGLE_NEWS_RSS = os.getenv("ENABLE_GOOGLE_NEWS_RSS", "1") == "1"
GOOGLE_NEWS_RSS_BASE   = os.getenv("GOOGLE_NEWS_RSS_BASE", "https://news.google.com/rss/search")

# Queries “tipo X”: cortas, enfocadas a sanciones/LAFT y región
GOOGLE_NEWS_QUERIES = [
    '(ofac OR "sdn list" OR "specially designated") (designated OR designation OR sanctioned OR sanctions)',
    '(FinCEN OR "money laundering") (indicted OR charged OR convicted)',
    '(Venezuela OR Maduro) (sanctions OR sanctioned OR "sanctions evasion")',
    '(Colombia) ("money laundering" OR narcotrafficking OR "terrorist financing")',
]

# ==============================
# Keywords (tu contexto)
# ==============================
KEYWORDS = [
    "ofac", "sdn", "sdn list", "specially designated", "specialy designated nationals",
    "designated", "designation", "blocked", "asset freeze",
    "sanction", "sanctions", "lista clinton", "lista de sanciones", "lista negra",
    "blacklist", "watchlist", "targeted sanctions",
    "money laundering", "laundering", "aml", "terrorism financing", "terrorist financing",
    "drug trafficking", "narcotrafficking", "corruption", "bribery",
    "lavado", "lavado de activos", "financiación del terrorismo", "corrupción", "soborno",
    "narcotráfico", "tráfico de drogas",
    "charged", "indicted", "accused", "convicted", "investigated",
    "acusado", "imputado", "condenado", "investigado", "sancionado",
    "colombia", "venezuela", "maduro",
]




# ==================


# Por defecto apagado 
ENABLE_X = os.getenv("ENABLE_X", "0") == "1"

# Alias legacy
ENABLE_TWITTER = ENABLE_X

# Límite de posts por fuente (si algún día tenemos la API de ENABLE_X=1)
MAX_TWEETS_PER_SOURCE = int(os.getenv("MAX_TWEETS_PER_SOURCE", "200"))

# Lista de cuentas 
TWITTER_SOURCES = [
    # "OFAC",
    # "USTreasury",
]
