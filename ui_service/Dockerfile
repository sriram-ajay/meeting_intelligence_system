FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --without dev --no-root && \
    rm -rf ~/.cache/pypoetry

COPY ui_service ./ui_service
COPY shared_utils ./shared_utils

ENV PYTHONPATH=/app
ENV ENVIRONMENT=production

EXPOSE 8501

CMD ["streamlit", "run", "ui_service/src/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false"]
