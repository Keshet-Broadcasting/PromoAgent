FROM python:3.12-slim

RUN adduser --disabled-password --gecos '' appuser

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN echo "=== Build-time verification ===" \
    && ls -la /code/ \
    && ls -la /code/app/ \
    && test -f /code/app/__init__.py \
    && test -f /code/app/api.py \
    && echo "OK: app package verified"

RUN chown -R appuser:appuser /code

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/code
ENV WEB_CONCURRENCY=2
EXPOSE 8000

USER appuser
CMD ["sh", "-c", "echo '=== Startup diag ===' && ls /code/app/ && python -c 'import app; print(app.__file__)' && uvicorn app.api:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
