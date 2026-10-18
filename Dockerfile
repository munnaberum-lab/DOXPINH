FROM python:3.12-slim

LABEL org.opencontainers.image.title="Dotxbrain Uptime Pro" \
      org.opencontainers.image.vendor="Dotxbrain" \
      org.opencontainers.image.description="Smart uptime monitor + Render wake-up Telegram bot with Mini App"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd -m botuser && chown -R botuser /app
USER botuser

EXPOSE 10000
CMD ["python", "main.py"]
