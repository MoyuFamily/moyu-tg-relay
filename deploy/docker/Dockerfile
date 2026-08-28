FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

RUN useradd --create-home --uid 10001 relay && \
    mkdir -p /app /data && \
    chown -R relay:relay /app /data

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY src /app/src/
COPY smoke_check.py /app/

USER relay

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python /app/smoke_check.py --base-url http://127.0.0.1:8787 || exit 1

CMD ["uvicorn", "moyu_tg_relay.app:app", "--host", "0.0.0.0", "--port", "8787"]
