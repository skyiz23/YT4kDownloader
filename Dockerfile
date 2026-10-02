# Deno's official image gives yt-dlp a supported JavaScript runtime
# without relying on a curl-based installer during the Render build.
FROM denoland/deno:latest

USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    DENO_NO_UPDATE_CHECK=1 \
    DENO_NO_PROMPT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-venv \
       ffmpeg \
       ca-certificates \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p downloads

# Verify the critical runtime pieces during the image build.
RUN deno --version && python --version && ffmpeg -version | head -n 1

EXPOSE 10000

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 600 app:app"]
