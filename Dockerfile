FROM python:3.11-slim

# Не буферизуем stdout/stderr — логи сразу видны в docker logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Зависимости отдельным слоем — кешируются при пересборке
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаём директорию для логов
RUN mkdir -p /app/logs

# Непривилегированный пользователь
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

COPY tg_bot.py .

CMD ["python", "tg_bot.py"]
