FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY apps/email/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/email/email_core.py apps/email/email_worker.py apps/email/email_observability.py ./
COPY apps/email/migrations ./migrations
COPY contracts/schemas/work-command.schema.json ./contracts/schemas/work-command.schema.json
COPY contracts/schemas/work/email-send-v1.schema.json ./contracts/schemas/work/email-send-v1.schema.json

USER 10001:10001
CMD ["python3", "email_worker.py"]
