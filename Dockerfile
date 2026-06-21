FROM python:3.12-slim

# ── OS security hardening ─────────────────────────────────────────────────────
# 1. Upgrade all packages to pull any available fixes from Debian repos.
# 2. Create non-root user *before* purging perl (adduser is a Perl script).
# 3. Purge packages that carry unfixed CVEs and are not needed at runtime:
#      - perl-base (CVE-2026-42496 CRITICAL, CVE-2026-8376 CRITICAL, + 3 HIGH):
#        only present because dpkg depends on it; the app never executes Perl.
#        --allow-remove-essential is required since perl-base is marked Essential.
#        dpkg is also removed as a side-effect — that is intentional and safe;
#        no further apt operations occur after this point.
#      - ncurses-bin (CVE-2025-69720 HIGH): CLI utilities (tput, reset, etc.)
#        not needed in a containerised server. The ncurses *libraries*
#        (libtinfo6, libncursesw6, ncurses-base) are kept — Python readline
#        links against them and they are covered by .trivyignore.
# Remaining unfixable CVEs are documented in .trivyignore.
RUN apt-get update \
    && apt-get upgrade -y \
    && adduser --disabled-password --gecos '' appuser \
    && apt-get purge -y ncurses-bin \
    && apt-get purge -y --allow-remove-essential perl-base \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

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

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

USER appuser
CMD ["sh", "-c", "echo '=== Startup diag ===' && ls /code/app/ && python -c 'import app; print(app.__file__)' && uvicorn app.api:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
