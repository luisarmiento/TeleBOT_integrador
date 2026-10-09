FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 bot

COPY *.py alembic.ini ./
COPY migrations ./migrations
USER bot
CMD ["python", "-u", "bot_corregido.py"]
