# KMA TAP production image for Google Cloud Run.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Seoul

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install -r requirements.txt

COPY . .
# Same tab branding step as the Render build command.
RUN python scripts/brand_streamlit_shell.py \
    && useradd --create-home --uid 10001 tap \
    && chown -R tap /app
USER tap

# Cloud Run injects PORT (8080); start_accounts.py reads it.
ENV PORT=8080
EXPOSE 8080
CMD ["python", "scripts/start_accounts.py"]
