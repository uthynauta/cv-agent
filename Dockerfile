FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Render SSH requires a shell-enabled account and a private SSH directory.
# "NP" is not a valid password hash, so password login remains unavailable.
RUN install -d -m 0700 /root/.ssh \
    && usermod --password 'NP' root

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENV DATA_DIR=/data

EXPOSE 8000

CMD ["uvicorn", "cv_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
