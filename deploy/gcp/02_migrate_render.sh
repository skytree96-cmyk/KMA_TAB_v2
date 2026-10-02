#!/usr/bin/env bash
# Copy the Render PostgreSQL database into Cloud SQL.
#
# Before running: in the Render dashboard, open kmatap-db > Networking and
# temporarily allow 0.0.0.0/0 (Cloud Build has no fixed IP). Remove it afterwards.
# Run this right before the cutover; writes to Render after the dump are not copied.
source "$(dirname "$0")/common.sh"

# --reset-url replaces a previously saved (e.g. mistyped) Render URL.
if [[ "${1:-}" == "--reset-url" ]] || ! secret_exists "$RENDER_URL_SECRET"; then
  echo "Render External Database URL을 붙여넣고 Enter (화면에 표시되지 않음, 한 번만 붙여넣기):"
  read -rs render_url
  echo
  render_url="$(printf '%s' "$render_url" | tr -d '[:space:]')"
  if [[ "$render_url" != postgres* ]] || [[ "$(grep -o 'postgres' <<<"$render_url" | wc -l)" -gt 2 ]] || [[ "$render_url" == *://*://* ]]; then
    echo "올바른 주소가 아닙니다 (postgresql://... 한 개만 붙여넣어 주세요)." >&2
    exit 1
  fi
  echo "입력 확인: ${render_url%%://*}://***@${render_url##*@}" | sed -E 's#(@[^.]{4})[^.]*#\1***#'
  if secret_exists "$RENDER_URL_SECRET"; then
    printf '%s' "$render_url" | gcloud secrets versions add "$RENDER_URL_SECRET" --data-file=-
  else
    printf '%s' "$render_url" | gcloud secrets create "$RENDER_URL_SECRET" --replication-policy=automatic --data-file=-
  fi
  unset render_url
fi
gcloud secrets add-iam-policy-binding "$RENDER_URL_SECRET" \
  --member="serviceAccount:$BUILD_SA" --role=roles/secretmanager.secretAccessor --quiet >/dev/null

gcloud storage buckets describe "$MIGRATION_BUCKET" >/dev/null 2>&1 \
  || gcloud storage buckets create "$MIGRATION_BUCKET" --location="$REGION" --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding "$MIGRATION_BUCKET" \
  --member="serviceAccount:$BUILD_SA" --role=roles/storage.objectAdmin --quiet >/dev/null
sql_sa="$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(serviceAccountEmailAddress)')"
gcloud storage buckets add-iam-policy-binding "$MIGRATION_BUCKET" \
  --member="serviceAccount:$sql_sa" --role=roles/storage.objectViewer --quiet >/dev/null

dump_uri="$MIGRATION_BUCKET/render-$(date +%Y%m%d-%H%M%S).sql"

build_config="$(mktemp)"
trap 'rm -f "$build_config"' EXIT
cat >"$build_config" <<YAML
steps:
  # pg_dump must be >= the Render server version (PostgreSQL 18).
  - name: postgres:18
    entrypoint: bash
    args:
      - -c
      - |
        set -euo pipefail
        pg_dump "\$\$RENDER_DATABASE_URL" --no-owner --no-privileges --format=plain --file=/workspace/dump.sql
        # Drop psql-only \\restrict/\\unrestrict guards that Cloud SQL import rejects.
        sed -i -E '/^\\\\(un)?restrict /d' /workspace/dump.sql
        echo "tables:"; grep -c '^CREATE TABLE' /workspace/dump.sql
    secretEnv: [RENDER_DATABASE_URL]
  - name: gcr.io/cloud-builders/gcloud
    args: [storage, cp, /workspace/dump.sql, "$dump_uri"]
availableSecrets:
  secretManager:
    - versionName: projects/$PROJECT_ID/secrets/$RENDER_URL_SECRET/versions/latest
      env: RENDER_DATABASE_URL
options:
  logging: CLOUD_LOGGING_ONLY
YAML

echo "== Dumping Render database via Cloud Build"
gcloud builds submit --no-source --region="$REGION" \
  --service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
  --config="$build_config"

echo "== Importing into Cloud SQL ($SQL_INSTANCE/$DB_NAME as $DB_USER)"
gcloud sql import sql "$SQL_INSTANCE" "$dump_uri" --database="$DB_NAME" --user="$DB_USER" --quiet

echo "== Removing dump (contains personal data)"
# Single process avoids a gcloud multiprocessing crash on Windows.
CLOUDSDK_STORAGE_PROCESS_COUNT=1 CLOUDSDK_STORAGE_THREAD_COUNT=1 gcloud storage rm "$dump_uri"

echo "Migration finished. Remove the 0.0.0.0/0 rule from Render, and delete the Render URL secret when done:"
echo "  gcloud secrets delete $RENDER_URL_SECRET"
