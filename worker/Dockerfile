FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-root && \
    rm -rf ~/.cache/pypoetry

COPY worker ./worker
COPY services ./services
COPY domain ./domain
COPY ports ./ports
COPY adapters ./adapters
COPY core_intelligence ./core_intelligence
COPY shared_utils ./shared_utils

RUN python -c "import nltk; nltk.download('punkt_tab'); nltk.download('punkt'); nltk.download('averaged_perceptron_tagger_eng')"

ENV PYTHONPATH=/app
ENV ENVIRONMENT=production

CMD ["python", "worker/entrypoint.py"]
