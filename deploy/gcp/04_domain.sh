#!/usr/bin/env bash
# Map the KMA subdomain to Cloud Run and print the DNS record for the IT team.
# Requires the logged-in account to be a verified owner of the domain in
# Google Search Console (see README).
source "$(dirname "$0")/common.sh"
: "${DOMAIN:?Set DOMAIN in config.env}"

if ! gcloud domains list-user-verified --format='value(id)' | grep -Eqx "${DOMAIN}|${DOMAIN#*.}"; then
  echo "$DOMAIN (or ${DOMAIN#*.}) is not verified for $(gcloud config get-value account 2>/dev/null)." >&2
  echo "Run: gcloud domains verify ${DOMAIN#*.}   (see deploy/gcp/README.md)" >&2
  exit 1
fi

gcloud beta run domain-mappings describe --domain="$DOMAIN" --region="$REGION" >/dev/null 2>&1 \
  || gcloud beta run domain-mappings create --service="$SERVICE" --domain="$DOMAIN" --region="$REGION"

echo "== DNS record to register (send to the KMA IT team):"
gcloud beta run domain-mappings describe --domain="$DOMAIN" --region="$REGION" \
  --format='table(status.resourceRecords[].name,status.resourceRecords[].type,status.resourceRecords[].rrdata)'
echo "TLS certificate is issued automatically after DNS propagates (15 min to 24 h)."
