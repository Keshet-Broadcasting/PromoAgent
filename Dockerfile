FROM python:3.11-slim

RUN adduser --disabled-password --gecos '' appuser

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R appuser:appuser /code

ENV PYTHONUNBUFFERED=1
ENV WEB_CONCURRENCY=2
EXPOSE 8000

USER appuser
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
