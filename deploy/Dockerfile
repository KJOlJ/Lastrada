FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    LASTRADA_CACHE_DIR=/tmp/lastrada/cache TORCH_HOME=/tmp/lastrada/torch \
    HF_HOME=/tmp/lastrada/huggingface PORT=8080
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" -o Acquire::Retries=0 -o Acquire::https::Timeout=20 update && apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY deploy/requirements-api.txt deploy/requirements-worker.txt deploy/
COPY src src
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca GIT_SSL_CAINFO=/run/secrets/build_ca; fi \
    && pip install --no-cache-dir -r deploy/requirements-worker.txt
COPY configs configs
RUN chmod -R a+rX /app
USER 65532:65532
CMD ["sh", "-c", "exec uvicorn lastrada.web.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
