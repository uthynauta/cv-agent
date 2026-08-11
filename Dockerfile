FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY README.md ./
COPY src ./src
COPY wiki ./wiki

RUN uv pip install --system .

EXPOSE 8000

CMD ["uvicorn", "banorte_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
