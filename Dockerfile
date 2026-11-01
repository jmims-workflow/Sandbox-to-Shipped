FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    STS_MODE=demo

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e .

EXPOSE 8080
CMD ["sh", "-c", "uvicorn sts.web:app --host 0.0.0.0 --port ${PORT:-8080}"]
