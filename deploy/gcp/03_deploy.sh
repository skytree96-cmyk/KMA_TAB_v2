#!/usr/bin/env bash
# Build the image with Cloud Build and deploy it to Cloud Run. Re-run for every release.
source "$(dirname "$0")/common.sh"

image="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO/$SERVICE:$(date +%Y%m%d-%H%M%S)"

echo "== Building $image"
gcloud builds submit "$REPO_ROOT" --region="$REGION" \
  --service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
  --config="$GCP_DIR/cloudbuild.yaml" --substitutions="_IMAGE=$image"

secrets="DATABASE_URL=$DB_URL_SECRET:latest"
# Only needed for an empty database; ignored once any user exists.
if secret_exists "$ADMIN_HASH_SECRET"; then
  gcloud secrets add-iam-policy-binding "$ADMIN_HASH_SECRET" \
    --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor --quiet >/dev/null
  secrets="$secrets,BOOTSTRAP_ADMIN_PASSWORD_HASH=$ADMIN_HASH_SECRET:latest"
fi

echo "== Deploying $SERVICE"
# Streamlit keeps per-browser state in memory over a websocket, so session
# affinity and a long request timeout are required.
gcloud run deploy "$SERVICE" --image="$image" --region="$REGION" \
  --service-account="$RUN_SA" \
  --add-cloudsql-instances="$SQL_CONNECTION" \
  --set-secrets="$secrets" \
  --set-env-vars="TAP_APP_MODE=production,GITHUB_DEMO_STORE_ENABLED=false,TAP_POSTGRES_PREFLIGHT=0,BOOTSTRAP_ADMIN_LOGIN=kma.admin" \
  --port=8080 --cpu=1 --memory=1Gi --concurrency=80 \
  --min-instances="${MIN_INSTANCES:-1}" --max-instances="${MAX_INSTANCES:-3}" \
  --session-affinity --timeout=3600 --cpu-boost \
  --allow-unauthenticated

gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)'
