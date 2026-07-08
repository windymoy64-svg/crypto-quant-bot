FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    BOT_API_HOST=0.0.0.0 \
    BOT_API_PORT=8899

WORKDIR /app

COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system bot \
    && useradd --system --gid bot --home-dir /app bot

COPY . .

RUN mkdir -p logs data configs logs/backtests \
    && chown -R bot:bot /app

USER bot


EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json, urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8899/health', timeout=3); raise SystemExit(0 if json.load(r).get('status') == 'ok' else 1)"

CMD ["python", "run_api.py"]
