#!/usr/bin/env bash
set -euo pipefail

CORE_NAME="addresses"
SOLR_URL="http://localhost:8983/solr"

echo "Starting Solr temporarily for initialization in standalone/user-managed mode..."
solr start --user-managed

echo "Waiting for Solr..."
until curl -fsS "$SOLR_URL/admin/info/system" >/dev/null; do
  sleep 2
done

if curl -fsS "$SOLR_URL/admin/cores?action=STATUS&core=$CORE_NAME&wt=json" | grep -q "\"$CORE_NAME\""; then
  echo "Core already exists: $CORE_NAME"
else
  echo "Creating core: $CORE_NAME"
  solr create_core -c "$CORE_NAME" -d _default
fi

echo "Applying schema for core: $CORE_NAME"
curl -i \
  -H "Content-Type: application/json" \
  -X POST \
  --data-binary @/addresses-schema.json \
  "$SOLR_URL/$CORE_NAME/schema"

echo "Stopping temporary Solr..."
solr stop -all

echo "Starting Solr in foreground in standalone/user-managed mode..."
exec solr-foreground --user-managed
