FROM python:3.12-slim

# Kerberos (ES_AUTH=kerberos): bibliotecas MIT e pacote python 'gssapi'
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libkrb5-3 libgssapi-krb5-2 krb5-user gcc libkrb5-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-kerberos.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-kerberos.txt \
    && apt-get purge -y gcc libkrb5-dev && apt-get autoremove -y

COPY app ./app

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
