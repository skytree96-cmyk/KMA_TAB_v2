# Shared settings for the deploy/gcp scripts. Sourced, not executed.
set -euo pipefail

GCP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$GCP_DIR/../.." && pwd)"

if [[ ! -f "$GCP_DIR/config.env" ]]; then
  echo "deploy/gcp/config.env is missing. Copy config.env.example and fill it in." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "$GCP_DIR/config.env"

: "${PROJECT_ID:?}" "${REGION:?}" "${SERVICE:?}" "${AR_REPO:?}" "${SQL_INSTANCE:?}" "${DB_NAME:?}" "${DB_USER:?}"

SQL_CONNECTION="$PROJECT_ID:$REGION:$SQL_INSTANCE"
RUN_SA="tap-run@$PROJECT_ID.iam.gserviceaccount.com"
BUILD_SA="tap-build@$PROJECT_ID.iam.gserviceaccount.com"
DB_URL_SECRET="tap-database-url"
ADMIN_HASH_SECRET="tap-bootstrap-admin-hash"
RENDER_URL_SECRET="render-database-url"
MIGRATION_BUCKET="gs://$PROJECT_ID-kmatap-migration"

gcloud config set project "$PROJECT_ID" >/dev/null

secret_exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }
