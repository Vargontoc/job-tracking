FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY source ./source
COPY config ./config

RUN pip install --no-cache-dir . uvicorn

EXPOSE 8000

CMD ["uvicorn", "source.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
