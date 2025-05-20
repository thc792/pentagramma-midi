# Scegli un'immagine Python di base (leggera)
FROM python:3.9-slim

# Imposta la directory di lavoro all'interno della "scatola"
WORKDIR /app

# Copia SOLO il file dei requisiti per ora
COPY api/requirements.txt .

# Installa le librerie Python elencate in requirements.txt
# L'opzione --no-cache-dir aiuta a mantenere l'immagine più piccola
RUN pip install --no-cache-dir -r requirements.txt

# Ora copia tutto il codice che si trova nella tua cartella 'api'
# dentro la cartella '/app' della "scatola"
COPY api/ /app/

# Diciamo a Vercel che la nostra applicazione dentro la "scatola"
# ascolterà sulla porta 8000 per le richieste
EXPOSE 8000

# Comando per avviare la tua applicazione Flask quando Vercel esegue la "scatola"
# 'index:app' significa: nel file index.py, avvia l'oggetto chiamato 'app' (che è la tua Flask app)
# Gunicorn è un server web robusto per applicazioni Python
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "index:app"]