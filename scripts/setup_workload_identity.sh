#!/bin/bash
# scripts/setup_workload_identity.sh
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

log()  { echo -e "${CYAN}► $1${RESET}"; }
ok()   { echo -e "${GREEN}✓ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠ $1${RESET}"; }

PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" \
    --format="value(projectNumber)")
REGION="asia-southeast1"
GITHUB_REPO="laspraharshana/a2a-marketplace"
SA_NAME="github-actions-deploy"
GH_SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo ""
echo "Setting up Workload Identity Federation..."
echo "Project: $PROJECT_ID ($PROJECT_NUMBER)"
echo "GitHub:  $GITHUB_REPO"
echo ""

# ── Step 1: Create Service Account ───────────────────────────
log "Creating GitHub Actions service account..."

# Check if already exists
if gcloud iam service-accounts describe "$GH_SA_EMAIL" \
    --project="$PROJECT_ID" &>/dev/null; then
    ok "Service account already exists: $GH_SA_EMAIL"
else
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="GitHub Actions Deploy" \
        --project="$PROJECT_ID"

    # Wait for GCP IAM eventual consistency
    log "Waiting for service account to propagate (30s)..."
    sleep 30

    # Verify it exists before proceeding
    MAX_RETRIES=5
    RETRY=0
    while ! gcloud iam service-accounts describe "$GH_SA_EMAIL" \
        --project="$PROJECT_ID" &>/dev/null; do
        RETRY=$((RETRY + 1))
        if [[ $RETRY -ge $MAX_RETRIES ]]; then
            echo -e "${RED}✗ Service account still not found after retries${RESET}"
            exit 1
        fi
        warn "Not ready yet, retrying in 10s ($RETRY/$MAX_RETRIES)..."
        sleep 10
    done
    ok "Service account ready: $GH_SA_EMAIL"
fi

# ── Step 2: Grant IAM Roles ───────────────────────────────────
log "Granting IAM roles to service account..."

ROLES=(
    "roles/run.admin"
    "roles/artifactregistry.writer"
    "roles/iam.serviceAccountUser"
    "roles/secretmanager.secretAccessor"
    "roles/cloudsql.client"
)

for role in "${ROLES[@]}"; do
    # Retry loop for each role binding
    for attempt in 1 2 3; do
        if gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:$GH_SA_EMAIL" \
            --role="$role" \
            --quiet 2>/dev/null; then
            echo "  ✓ Granted: $role"
            break
        else
            if [[ $attempt -lt 3 ]]; then
                warn "  Retry $attempt for $role..."
                sleep 10
            else
                echo -e "  ${RED}✗ Failed: $role (after 3 attempts)${RESET}"
            fi
        fi
    done
done

ok "IAM roles granted"

# ── Step 3: Workload Identity Pool ───────────────────────────
log "Creating Workload Identity Pool..."

if gcloud iam workload-identity-pools describe \
    "github-actions-pool" \
    --location="global" \
    --project="$PROJECT_ID" &>/dev/null; then
    ok "Pool already exists"
else
    gcloud iam workload-identity-pools create "github-actions-pool" \
        --location="global" \
        --display-name="GitHub Actions Pool" \
        --project="$PROJECT_ID"
    ok "Pool created"
fi

# ── Step 4: OIDC Provider ────────────────────────────────────
log "Creating OIDC Provider..."

if gcloud iam workload-identity-pools providers describe \
    "github-provider" \
    --location="global" \
    --workload-identity-pool="github-actions-pool" \
    --project="$PROJECT_ID" &>/dev/null; then
    ok "Provider already exists"
else
    gcloud iam workload-identity-pools providers create-oidc \
        "github-provider" \
        --location="global" \
        --workload-identity-pool="github-actions-pool" \
        --display-name="GitHub Provider" \
        --attribute-mapping="\
google.subject=assertion.sub,\
attribute.actor=assertion.actor,\
attribute.repository=assertion.repository" \
        --issuer-uri="https://token.actions.githubusercontent.com" \
        --project="$PROJECT_ID"
    ok "Provider created"
fi

# ── Step 5: Bind GitHub Repo to Service Account ───────────────
log "Binding GitHub repo to service account..."

POOL_RESOURCE="projects/$PROJECT_NUMBER/locations/global\
/workloadIdentityPools/github-actions-pool"

gcloud iam service-accounts add-iam-policy-binding \
    "$GH_SA_EMAIL" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/$POOL_RESOURCE/attribute.repository/$GITHUB_REPO" \
    --project="$PROJECT_ID" \
    --quiet

ok "GitHub repo bound to service account"

# ── Step 6: Get Output Values ────────────────────────────────
WORKLOAD_IDENTITY_PROVIDER=$(gcloud iam workload-identity-pools \
    providers describe "github-provider" \
    --location="global" \
    --workload-identity-pool="github-actions-pool" \
    --project="$PROJECT_ID" \
    --format="value(name)")

DB_CONNECTION=$(gcloud sql instances describe "a2a-postgres" \
    --project="$PROJECT_ID" \
    --format="value(connectionName)" 2>/dev/null || echo "")

A2A_TOKEN=$(gcloud secrets versions access latest \
    --secret="A2A_BEARER_TOKEN" \
    --project="$PROJECT_ID" 2>/dev/null || echo "")

# ── Step 7: Print GitHub Secrets ─────────────────────────────
echo ""
echo "════════════════════════════════════════════════════"
echo "  COPY THESE TO GITHUB SECRETS"
echo "  URL: https://github.com/$GITHUB_REPO"
echo "       /settings/secrets/actions"
echo "════════════════════════════════════════════════════"
echo ""
echo "Secret Name           | Value"
echo "─────────────────────────────────────────────────────"
echo "GCP_PROJECT_ID        | $PROJECT_ID"
echo "GCP_REGION            | $REGION"
echo "GCP_SERVICE_ACCOUNT   | $GH_SA_EMAIL"
echo "DB_CONNECTION_NAME    | $DB_CONNECTION"
echo "A2A_BEARER_TOKEN      | $A2A_TOKEN"
echo ""
echo "GCP_WORKLOAD_IDENTITY |"
echo "$WORKLOAD_IDENTITY_PROVIDER"
echo ""
echo "════════════════════════════════════════════════════"
echo ""
ok "Setup complete — add the values above to GitHub Secrets"