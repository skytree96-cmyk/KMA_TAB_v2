#!/usr/bin/env bash
# One-time setup: let GitHub Actions deploy main to Cloud Run without a key file.
# Run once as a project owner:  bash deploy/gcp/05_github_deploy.sh
# Safe to re-run; existing resources are kept.
#
# What it grants, and to whom:
#   - Workload identity pool "github" / provider "kma-tab-v2": accepts only tokens of
#     $GITHUB_REPO on refs/heads/main, so pull requests and forks cannot use it.
#   - Service account tap-deploy: may deploy the Cloud Run service, start Cloud Build,
#     upload build sources and act as the build and run service accounts. It cannot read
#     secret values or the database.
source "$(dirname "$0")/common.sh"

GITHUB_REPO="${GITHUB_REPO:-skytree96-cmyk/KMA_TAB_v2}"
POOL="github"
PROVIDER="kma-tab-v2"
DEPLOY_SA="tap-deploy@$PROJECT_ID.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
BUILD_BUCKET="gs://${PROJECT_ID}_cloudbuild"

echo "== APIs"
gcloud services enable sts.googleapis.com iamcredentials.googleapis.com

echo "== Deployer service account"
gcloud iam service-accounts describe "$DEPLOY_SA" >/dev/null 2>&1 \
  || gcloud iam service-accounts create tap-deploy --display-name="TAP GitHub Actions deployer"

echo "== Workload identity (repository $GITHUB_REPO, main only)"
gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "$POOL" --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global --workload-identity-pool="$POOL" >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location=global --workload-identity-pool="$POOL" \
       --display-name="KMA_TAB_v2 main" --issuer-uri="https://token.actions.githubusercontent.com" \
       --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
       --attribute-condition="assertion.repository=='$GITHUB_REPO' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role=roles/iam.workloadIdentityUser --quiet >/dev/null \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$GITHUB_REPO"

echo "== Deploy permissions for $DEPLOY_SA"
for role in roles/cloudbuild.builds.editor roles/serviceusage.serviceUsageConsumer roles/logging.viewer \
            roles/secretmanager.viewer roles/cloudsql.viewer roles/artifactregistry.reader; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOY_SA" --role="$role" \
    --condition=None --quiet >/dev/null
done
# Only this one service, not every Cloud Run service in the project.
gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/run.admin --quiet >/dev/null
# Build sources are uploaded to the Cloud Build bucket.
gcloud storage buckets add-iam-policy-binding "$BUILD_BUCKET" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/storage.admin --quiet >/dev/null
for account in "$BUILD_SA" "$RUN_SA"; do
  gcloud iam service-accounts add-iam-policy-binding "$account" \
    --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser --quiet >/dev/null
done

PROVIDER_NAME="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"
echo "== GitHub repository variables"
if command -v gh >/dev/null 2>&1; then
  gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$GITHUB_REPO" --body "$PROVIDER_NAME"
  gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --repo "$GITHUB_REPO" --body "$DEPLOY_SA"
  # config.env holds non-secret values only (see config.env.example).
  gh variable set GCP_DEPLOY_CONFIG --repo "$GITHUB_REPO" --body "$(grep -v '^\s*#' "$GCP_DIR/config.env" | grep -v '^\s*$')"
  echo "Variables set on $GITHUB_REPO."
else
  echo "gh is not installed. Set these repository variables by hand (Settings > Secrets and variables > Actions > Variables):"
  echo "  GCP_WORKLOAD_IDENTITY_PROVIDER = $PROVIDER_NAME"
  echo "  GCP_DEPLOY_SERVICE_ACCOUNT     = $DEPLOY_SA"
  echo "  GCP_DEPLOY_CONFIG              = (contents of deploy/gcp/config.env without comments)"
fi
echo "Done. A merge into main now deploys after the validation workflow passes."
