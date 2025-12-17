OFAC SOCIAL MEDIA MONITOR (Web)
================================

Qué hace
--------
1) Descarga y mantiene un índice local de la lista OFAC SDN (archivo oficial).
2) Cada N segundos/minutos consulta fuentes (RSS + opcional Twitter vía snscrape),
   detecta menciones relevantes por keywords, extrae PERSON con spaCy.
3) Cruza los nombres extraídos contra OFAC SDN y muestra:
   - "Posible match OFAC" (score alto)
   - "Candidato por contexto" (mencionado pero no hace match)

IMPORTANTE
----------
- Esto NO declara que alguien "es sancionado" por una noticia o un tweet.
  Solo muestra coincidencias posibles y evidencia (texto + fuente) para revisión humana.
- Respeta términos de uso de tus fuentes. Para X/Twitter se recomienda API oficial.

Cómo correr (local)
-------------------
1) Crear entorno:
   python -m venv .venv
   .venv\Scripts\activate   (Windows)
   pip install -r requirements.txt

2) Modelos spaCy:
   python -m spacy download en_core_web_sm
   (opcional) python -m spacy download es_core_news_sm

3) Iniciar servidor:
   uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000

4) Abrir:
   http://localhost:8000

