FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    FED_CONFIG_DIR=/srv/config

WORKDIR /srv/app

COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app/ /srv/app/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
