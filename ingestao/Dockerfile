FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY enade ./enade
COPY mapping ./mapping
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "enade.consumidor"]
