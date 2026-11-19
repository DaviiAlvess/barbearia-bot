FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Bahia
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m bot && mkdir -p /app/dados && chown -R bot /app
USER bot
ENV BANCO=/app/dados/barbearia.db
CMD ["python", "bot_whatsapp.py"]
