# Ubuntu 26.04 LTS 기본 Python(3.14) 기준
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# 루트로 돌리지 않는다
RUN useradd --create-home --uid 10001 bot \
 && mkdir -p /app/data \
 && chown -R bot:bot /app
USER bot

VOLUME ["/app/data"]

CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]
