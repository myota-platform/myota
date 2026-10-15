FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY email_core.py email_worker.py ./
COPY migrations ./migrations

USER 10001:10001
CMD ["python3", "email_worker.py"]
