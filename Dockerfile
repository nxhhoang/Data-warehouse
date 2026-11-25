FROM python:3.11-slim-bookworm

ARG CLOUD_SDK_VERSION=594.0.1
ENV CLOUDSDK_PYTHON_SITEPACKAGES=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    PATH="/app/.venv/bin:/opt/google-cloud-sdk/bin:${PATH}"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates curl default-jre-headless git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-${CLOUD_SDK_VERSION}-linux-x86_64.tar.gz" \
        | tar -xz -C /opt \
    && gcloud components install pubsub-emulator beta --quiet

WORKDIR /app
COPY requirements.txt ./
RUN python -m venv .venv \
    && .venv/bin/pip install --no-cache-dir --upgrade pip \
    && .venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .
ENTRYPOINT ["bash", "scripts/docker-entrypoint.sh"]
CMD ["replay"]
