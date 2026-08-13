#!/bin/bash
# scripts/setup_secrets.sh
# Run this separately after setup_gcp.sh stops
# ══════════════════════════════════════════════

set -euo pipefail

PROJECT_ID=$(gcloud config get-value project)
DB_INSTANCE="a2a-postgres"
DB_NAME="a2a_marketplace"
DB_USER="a2a"

echo "Loading secrets for project: $PROJECT_ID"

# ── Read .env file ────────────────────────────
if [[ ! -f ".env" ]]; then
    echo "ERROR: .env not found"
    exit 1
fi

# Safe way to read .env
declare -A ENV_VARS
while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ "$key" =~ ^#.*$ ]] && continue
    [[ -z "$key" ]] && continue
    # Trim whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    ENV_VARS["$key"]="$value"
done < .env

# ── Function to create/update secret ──────────
upsert_secret() {
    local name=$1
    local value=$2

    if [[ -z "$value" ]]; then
        echo "⚠  SKIPPING $name (empty value)"
        return
    fi

    # Check if secret exists
    if gcloud secrets describe "$name" \
        --project="$PROJECT_ID" \
        &>/dev/null; then
        # Update existing secret
        echo -n "$value" | gcloud secrets versions add "$name" \
            --data-file=- \
            --project="$PROJECT_ID" \
            --quiet
        echo "✓ Updated secret: $name"
    else
        # Create new secret
        echo -n "$value" | gcloud secrets create "$name" \
            --data-file=- \
            --replication-policy="automatic" \
            --project="$PROJECT_ID" \
            --quiet
        echo "✓ Created secret: $name"
    fi
}

# ── Get DB password (generated during setup) ──
# If you saved it from setup_gcp.sh output, paste here
# Otherwise generate a new one
DB_PASSWORD=$(gcloud secrets versions access latest \
    --secret="DB_PASSWORD" \
    --project="$PROJECT_ID" 2>/dev/null || \
    python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# ── Build PostgreSQL URL for Cloud SQL ────────
DB_CONNECTION=$(gcloud sql instances describe "$DB_INSTANCE" \
    --project="$PROJECT_ID" \
    --format="value(connectionName)" 2>/dev/null || echo "")

if [[ -n "$DB_CONNECTION" ]]; then
    POSTGRES_URL="postgresql://$DB_USER:$DB_PASSWORD@/$DB_NAME?host=/cloudsql/$DB_CONNECTION"
    echo "DB Connection: $DB_CONNECTION"
    echo "Postgres URL built: postgresql://$DB_USER:****@/$DB_NAME?host=/cloudsql/$DB_CONNECTION"
else
    echo "WARNING: Could not get DB connection name"
    POSTGRES_URL="${ENV_VARS[POSTGRES_URL]:-}"
fi

# ── Store all secrets ─────────────────────────
echo ""
echo "Storing secrets in Secret Manager..."
echo "────────────────────────────────────────"

upsert_secret "GOOGLE_API_KEY" \
    "${ENV_VARS[GOOGLE_API_KEY]:-}"

upsert_secret "GOOGLE_SEARCH_API_KEY" \
    "${ENV_VARS[GOOGLE_SEARCH_API_KEY]:-}"

upsert_secret "GOOGLE_SEARCH_ENGINE_ID" \
    "${ENV_VARS[GOOGLE_SEARCH_ENGINE_ID]:-}"

upsert_secret "JWT_SECRET_KEY" \
    "${ENV_VARS[JWT_SECRET_KEY]:-}"

upsert_secret "A2A_BEARER_TOKEN" \
    "${ENV_VARS[A2A_BEARER_TOKEN]:-}"

upsert_secret "AGENT_MODEL" \
    "${ENV_VARS[AGENT_MODEL]:-gemini-flash-lite-latest}"

upsert_secret "ORCHESTRATOR_MODEL" \
    "${ENV_VARS[ORCHESTRATOR_MODEL]:-gemini-flash-latest}"

upsert_secret "DB_PASSWORD" \
    "$DB_PASSWORD"

upsert_secret "POSTGRES_URL" \
    "$POSTGRES_URL"

echo ""
echo "────────────────────────────────────────"
echo "✓ All secrets stored"

# ── Verify ────────────────────────────────────
echo ""
echo "Verifying secrets:"
gcloud secrets list \
    --project="$PROJECT_ID" \
    --format="table(name,createTime.date())"