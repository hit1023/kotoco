FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng libsndfile1 build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir "kokoro>=0.9.4" "misaki[ja]" fastapi "uvicorn[standard]" soundfile numpy
RUN python -m unidic download
COPY app/ /srv/app/
ENV HF_HOME=/cache/hf
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
