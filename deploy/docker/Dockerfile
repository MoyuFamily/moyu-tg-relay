FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 relay && \
    mkdir -p /app /data && \
    chown -R relay:relay /app /data

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src/
RUN pip install --no-cache-dir .

COPY smoke_check.py /app/

USER relay

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "from urllib.request import urlopen; r=urlopen('http://127.0.0.1:8787/readyz', timeout=3); raise SystemExit(0 if r.status == 200 else 1)" || exit 1

CMD ["uvicorn", "moyu_tg_relay.app:app", "--host", "0.0.0.0", "--port", "8787"]
