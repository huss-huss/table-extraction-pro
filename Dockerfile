# syntax=docker/dockerfile:1
#
# Build:   docker build -t table-extraction-pro .                       (fallback parsers, no torch)
#          docker build --build-arg EXTRAS=ml,fallback -t table-extraction-pro:ml .
#          docker build --build-arg EXTRAS= -t table-extraction-pro:base .  (base install only)
# Run:     docker run -p 8000:8000 table-extraction-pro

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder
ARG EXTRAS=fallback
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY table_extraction ./table_extraction
# CPU-only torch wheels keep the ml image several GB smaller than the default CUDA build.
RUN if [ -n "$EXTRAS" ]; then SPEC=".[${EXTRAS}]"; else SPEC="."; fi \
    && case ",$EXTRAS," in \
         *,ml,*) pip install --extra-index-url https://download.pytorch.org/whl/cpu "$SPEC" ;; \
         *) pip install "$SPEC" ;; \
       esac

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG EXTRAS=fallback
# Tabula needs a Java runtime; only installed when the fallback extra is.
RUN case ",$EXTRAS," in \
      *,fallback,*) apt-get update \
        && apt-get install -y --no-install-recommends default-jre-headless \
        && rm -rf /var/lib/apt/lists/* ;; \
    esac \
    && useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/app/.cache/huggingface \
    TEP_MAX_UPLOAD_MB=20
USER app
WORKDIR /home/app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status != 200)"
CMD ["uvicorn", "table_extraction.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
