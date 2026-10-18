# syntax=docker/dockerfile:1
# Base pinned by digest so every build uses the same bytes; Dependabot proposes digest updates.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

# ---- build stage: install dependencies into an isolated venv ----
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime stage: no pip cache, no build leftovers ----
FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="tenant-operator" \
      org.opencontainers.image.description="Kubernetes operator that onboards teams onto a shared private cluster" \
      org.opencontainers.image.source="https://github.com/Arun-Singh-Chauhan-09/private-cloud-tenant-operator" \
      org.opencontainers.image.licenses="MIT"

# System user: fixed UID/GID, no home directory, no login shell.
RUN groupadd --system --gid 10001 tenantop \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin tenantop

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Code and venv stay owned by root, so the running process cannot modify its own code.
COPY --from=build /opt/venv /opt/venv
COPY tenant_operator/ tenant_operator/

USER 10001:10001
EXPOSE 8080 8081
ENTRYPOINT ["kopf", "run", "--standalone", "--all-namespaces", "--liveness=http://0.0.0.0:8081/healthz", "-m", "tenant_operator.handlers"]
