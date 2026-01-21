FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     DATA_DIR=/data     OUTPUT_DIR=/output     PORT=8787

WORKDIR /app

# System deps (+ vim)
RUN apt-get update && apt-get install -y --no-install-recommends \
     ca-certificates \
     vim \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

EXPOSE 8787
CMD ["python", "-m", "app.main"]
