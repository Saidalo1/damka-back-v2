FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install build tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        make \
        gettext \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Copy scripts
COPY ./compose/django/entrypoint /entrypoint
RUN sed -i 's/\r$//' /entrypoint && chmod +x /entrypoint

COPY ./compose/django/start /start
RUN sed -i 's/\r$//' /start && chmod +x /start

COPY ./compose/django/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//' /start-celeryworker && chmod +x /start-celeryworker

WORKDIR /app
COPY . /app

ENTRYPOINT ["/entrypoint"]
