# Built from the repo root (see docker-compose.yml): needs backend/ and widget/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ /code/
COPY widget/ /widget/

# Run as a normal user, not root.
RUN useradd --create-home bot && chown -R bot /code /widget
USER bot

EXPOSE 8000
# --proxy-headers: behind Nginx / Cloudflare, take the visitor's IP from
# X-Forwarded-For (only from the proxies listed in FORWARDED_ALLOW_IPS), so
# rate limits count each visitor, not the proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
