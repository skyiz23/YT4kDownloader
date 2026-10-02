FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    YTDL_POT_PROVIDER_URL=http://127.0.0.1:4416

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg ca-certificates nodejs npm git \
    && rm -rf /var/lib/apt/lists/*

# BgUtils 2.0.0 must match the Python plugin version.
RUN git clone --depth 1 --branch 2.0.0 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server \
    && npm ci --omit=dev --no-audit --no-fund \
    && npm ci --no-audit --no-fund \
    && npx tsc

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt

COPY . .
RUN mkdir -p downloads

EXPOSE 10000

CMD ["sh", "-c", "node /opt/bgutil/server/build/main.js --host 127.0.0.1 --port 4416 & exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 600 app:app"]
