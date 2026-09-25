# Imagen de la API. La interfaz Streamlit es de uso personal y no se incluye.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# Detrás de un proxy corporativo que inspecciona HTTPS, pase su certificado:
#   docker build --secret id=ca_extra,src=/ruta/ca.crt .
# El secreto no queda en la imagen.
RUN --mount=type=secret,id=ca_extra,required=false \
    if [ -f /run/secrets/ca_extra ]; then export PIP_CERT=/run/secrets/ca_extra; fi; \
    pip install ".[api,postgres,excel]"
COPY alembic.ini ./
COPY migrations ./migrations
COPY datos ./datos

RUN useradd --create-home --uid 10001 portafolio
USER portafolio

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=3)"
CMD ["python", "-m", "portafolio", "api", "--host", "0.0.0.0", "--puerto", "8000"]
