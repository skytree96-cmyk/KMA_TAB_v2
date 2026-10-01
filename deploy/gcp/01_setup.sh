#!/usr/bin/env bash
# One-time infrastructure: APIs, Artifact Registry, Cloud SQL, secrets, service accounts.
# Safe to re-run; existing resources are left untouched.
source "$(dirname "$0")/common.sh"

echo "== Enabling APIs"
gcloud services enable run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com iam.googleapis.com

echo "== Artifact Registry"
gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location="$REGION"

echo "== Cloud SQL instance (takes several minutes on first run)"
if ! gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$SQL_INSTANCE" \
    --database-version=POSTGRES_18 --edition=ENTERPRISE --tier=db-f1-micro \
    --region="$REGION" --availability-type=zonal \
    --storage-type=SSD --storage-size=10 --storage-auto-increase \
    --backup-start-time=18:00 --retained-backups-count=14 \
    --database-flags=timezone=Asia/Seoul
fi
gcloud sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" >/dev/null 2>&1 \
  || gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE"

echo "== Database user and DATABASE_URL secret"
if ! secret_exists "$DB_URL_SECRET"; then
  # Hex keeps the password URL-safe. It is stored only in Secret Manager.
  db_password="$(openssl rand -hex 24)"
  if gcloud sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
    gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --password="$db_password"
  else
    gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$db_password"
  fi
  printf '%s' "postgresql://$DB_USER:$db_password@/$DB_NAME?host=/cloudsql/$SQL_CONNECTION" \
    | gcloud secrets create "$DB_URL_SECRET" --replication-policy=automatic --data-file=-
  unset db_password
fi

echo "== Service accounts"
for sa in tap-run tap-build; do
  gcloud iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "$sa" --display-name="KMA TAP $sa"
done

bind_project() {
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$1" --role="$2" \
    --condition=None --quiet >/dev/null
}
bind_project "$RUN_SA" roles/cloudsql.client
bind_project "$BUILD_SA" roles/logging.logWriter
bind_project "$BUILD_SA" roles/storage.objectViewer
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:$BUILD_SA" --role=roles/artifactregistry.writer --quiet >/dev/null
gcloud secrets add-iam-policy-binding "$DB_URL_SECRET" \
  --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor --quiet >/dev/null
# Lets whoever runs 03_deploy.sh build as tap-build.
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" \
  --member="user:$(gcloud config get-value account 2>/dev/null)" --role=roles/iam.serviceAccountUser --quiet >/dev/null

echo "Setup complete. Cloud SQL connection: $SQL_CONNECTION"
