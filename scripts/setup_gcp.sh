#!/bin/bash
# scripts/setup_gcp.sh
# ══════════════════════════════════════════════════════════════
# One-time GCP infrastructure setup for A2A Marketplace
# Run once before first deployment.
#
# Usage:
#   chmod +x scripts/setup_gcp.sh
#   ./scripts/setup_gcp.sh
# ══════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'
BOLD='\033[1m'

log()  { echo -e "${CYAN}► $1${RESET}"; }
ok()   { echo -e "${GREEN}✓ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠ $1${RESET}"; }
err()  { echo -e "${RED}✗ $1${RESET}"; exit 1; }

# ── Configuration ─────────────────────────────────────────────
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
REGION="asia-southeast1"          # Singapore region
DB_INSTANCE="a2a-postgres"
DB_NAME="a2a_marketplace"
DB_USER="a2a"
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
AR_REPO="a2a-marketplace"         # Artifact Registry repo name
GITHUB_REPO="laspraharshana/a2a-marketplace"

if [[ -z "$PROJECT_ID" ]]; then
    err "No GCP project set. Run: gcloud init"
fi

echo ""
echo -e "${BOLD}A2A Marketplace — GCP Setup${RESET}"
echo -e "${CYAN}══════════════════════════════════════════${RESET}"
echo -e "Project:  ${BOLD}$PROJECT_ID${RESET}"
echo -e "Region:   ${BOLD}$REGION${RESET}"
echo -e "GitHub:   ${BOLD}$GITHUB_REPO${RESET}"
echo ""
read -p "Continue? (y/N): " confirm
[[ "$confirm" == "y" || "$confirm" == "Y" ]] || exit 0

# ── Step 1: Enable APIs ───────────────────────────────────────
log "Enabling GCP APIs..."
gcloud services enable \
    run.googleapis.com \
    sqladmin.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com \
    iam.googleapis.com \
    cloudresourcemanager.googleapis.com \
    --project="$PROJECT_ID"
ok "APIs enabled"

# ── Step 2: Artifact Registry ─────────────────────────────────
log "Creating Artifact Registry repository..."
gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="A2A Marketplace Docker images" \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "Artifact Registry repo already exists"
ok "Artifact Registry ready: $REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO"

# ── Step 3: Cloud SQL ─────────────────────────────────────────
log "Creating Cloud SQL PostgreSQL instance (takes 5-10 mins)..."
gcloud sql instances create "$DB_INSTANCE" \
    --database-version=POSTGRES_15 \
    --tier=db-f1-micro \
    --region="$REGION" \
    --storage-type=HDD \
    --storage-size=10GB \
    --no-backup \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "Cloud SQL instance already exists"
ok "Cloud SQL instance created"

log "Creating database..."
gcloud sql databases create "$DB_NAME" \
    --instance="$DB_INSTANCE" \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "Database already exists"

log "Creating database user..."
gcloud sql users create "$DB_USER" \
    --instance="$DB_INSTANCE" \
    --password="$DB_PASSWORD" \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "User already exists"
ok "Cloud SQL database ready"

# Get connection name for Cloud Run
DB_CONNECTION_NAME=$(gcloud sql instances describe "$DB_INSTANCE" \
    --project="$PROJECT_ID" \
    --format="value(connectionName)")
ok "DB connection name: $DB_CONNECTION_NAME"

# ── Step 4: Service Account ───────────────────────────────────
log "Creating service account..."
SA_NAME="a2a-cloudrun"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SA_NAME" \
    --display-name="A2A Marketplace Cloud Run SA" \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "Service account already exists"

# Grant required roles
for role in \
    "roles/cloudsql.client" \
    "roles/secretmanager.secretAccessor" \
    "roles/run.invoker"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="$role" \
        --quiet
done
ok "Service account configured: $SA_EMAIL"

# ── Step 5: Secret Manager ────────────────────────────────────
log "Loading secrets from .env file..."
if [[ ! -f ".env" ]]; then
    err ".env file not found. Run from project root."
fi

source_secret() {
    local secret_name=$1
    local secret_value=$2
    echo -n "$secret_value" | \
        gcloud secrets create "$secret_name" \
            --data-file=- \
            --project="$PROJECT_ID" 2>/dev/null || \
    echo -n "$secret_value" | \
        gcloud secrets versions add "$secret_name" \
            --data-file=- \
            --project="$PROJECT_ID"
}

# Read values from .env
GOOGLE_API_KEY=$(grep "^GOOGLE_API_KEY=" .env | cut -d'=' -f2-)
GOOGLE_SEARCH_API_KEY=$(grep "^GOOGLE_SEARCH_API_KEY=" .env | cut -d'=' -f2-)
GOOGLE_SEARCH_ENGINE_ID=$(grep "^GOOGLE_SEARCH_ENGINE_ID=" .env | cut -d'=' -f2-)
JWT_SECRET_KEY=$(grep "^JWT_SECRET_KEY=" .env | cut -d'=' -f2-)
A2A_BEARER_TOKEN=$(grep "^A2A_BEARER_TOKEN=" .env | cut -d'=' -f2-)
AGENT_MODEL=$(grep "^AGENT_MODEL=" .env | cut -d'=' -f2-)
ORCHESTRATOR_MODEL=$(grep "^ORCHESTRATOR_MODEL=" .env | cut -d'=' -f2-)

# Build postgres URL for Cloud SQL
POSTGRES_URL="postgresql+asyncpg://$DB_USER:$DB_PASSWORD@/$DB_NAME?host=/cloudsql/$DB_CONNECTION_NAME"
# asyncpg-compatible URL for Cloud SQL Unix socket
POSTGRES_URL_ASYNCPG="postgresql://$DB_USER:$DB_PASSWORD@/$DB_NAME?host=/cloudsql/$DB_CONNECTION_NAME"

source_secret "GOOGLE_API_KEY"          "$GOOGLE_API_KEY"
source_secret "GOOGLE_SEARCH_API_KEY"   "$GOOGLE_SEARCH_API_KEY"
source_secret "GOOGLE_SEARCH_ENGINE_ID" "$GOOGLE_SEARCH_ENGINE_ID"
source_secret "JWT_SECRET_KEY"          "$JWT_SECRET_KEY"
source_secret "A2A_BEARER_TOKEN"        "$A2A_BEARER_TOKEN"
source_secret "AGENT_MODEL"             "$AGENT_MODEL"
source_secret "ORCHESTRATOR_MODEL"      "$ORCHESTRATOR_MODEL"
source_secret "DB_PASSWORD"             "$DB_PASSWORD"
source_secret "POSTGRES_URL"            "$POSTGRES_URL_ASYNCPG"

ok "All secrets stored in Secret Manager"

# ── Step 6: GitHub Actions Service Account ────────────────────
log "Creating GitHub Actions deployment service account..."
GH_SA_NAME="github-actions-deploy"
GH_SA_EMAIL="$GH_SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$GH_SA_NAME" \
    --display-name="GitHub Actions Deploy SA" \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "GitHub Actions SA already exists"

for role in \
    "roles/run.admin" \
    "roles/artifactregistry.writer" \
    "roles/iam.serviceAccountUser" \
    "roles/secretmanager.secretAccessor"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$GH_SA_EMAIL" \
        --role="$role" \
        --quiet
done

# Create and download key for GitHub Actions
gcloud iam service-accounts keys create \
    /tmp/github-actions-key.json \
    --iam-account="$GH_SA_EMAIL" \
    --project="$PROJECT_ID"

ok "GitHub Actions SA configured"

# ── Step 7: Workload Identity Federation (better than key) ────
log "Setting up Workload Identity Federation..."
POOL_NAME="github-actions-pool"
PROVIDER_NAME="github-provider"

gcloud iam workload-identity-pools create "$POOL_NAME" \
    --location="global" \
    --display-name="GitHub Actions Pool" \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "Pool already exists"

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_NAME" \
    --location="global" \
    --workload-identity-pool="$POOL_NAME" \
    --display-name="GitHub Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --project="$PROJECT_ID" 2>/dev/null || \
    warn "Provider already exists"

WORKLOAD_IDENTITY_PROVIDER=$(gcloud iam workload-identity-pools providers describe "$PROVIDER_NAME" \
    --location="global" \
    --workload-identity-pool="$POOL_NAME" \
    --project="$PROJECT_ID" \
    --format="value(name)")

# Allow GitHub repo to impersonate the SA
gcloud iam service-accounts add-iam-policy-binding "$GH_SA_EMAIL" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/$WORKLOAD_IDENTITY_PROVIDER/attribute.repository/$GITHUB_REPO" \
    --project="$PROJECT_ID"

ok "Workload Identity Federation configured"

# ── Step 8: Print Summary ─────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  GCP Setup Complete!${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}Add these to GitHub Secrets:${RESET}"
echo -e "${CYAN}(Settings → Secrets → Actions → New repository secret)${RESET}"
echo ""
echo -e "GCP_PROJECT_ID:           ${BOLD}$PROJECT_ID${RESET}"
echo -e "GCP_REGION:               ${BOLD}$REGION${RESET}"
echo -e "GCP_WORKLOAD_IDENTITY:    ${BOLD}$WORKLOAD_IDENTITY_PROVIDER${RESET}"
echo -e "GCP_SERVICE_ACCOUNT:      ${BOLD}$GH_SA_EMAIL${RESET}"
echo -e "DB_CONNECTION_NAME:       ${BOLD}$DB_CONNECTION_NAME${RESET}"
echo ""
echo -e "${YELLOW}Save DB password securely:${RESET}"
echo -e "DB_PASSWORD: ${BOLD}$DB_PASSWORD${RESET}"
echo ""
echo -e "${BOLD}Artifact Registry:${RESET}"
echo -e "$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO"
echo ""