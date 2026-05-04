#!/usr/bin/env bash
# Provision Azure resources for the firefly-mcp deployment.
# Idempotent: safe to re-run. Requires `az login` with permissions on rg-firefly.

set -euo pipefail

SUB="e8b8063e-f842-4a59-9754-427ddb7bfb63"
RG="rg-firefly"
LOC="spaincentral"

LAW="firefly-logs"
ACR="fireflysignature"
SA="fireflysignature"
BLOB_CONTAINER="firefly-artifacts"
KV="kv-firefly-signature"
MI="firefly-mcp-mi"
ENV_NAME="firefly-env"
APP="firefly-mcp"
IMAGE="${ACR}.azurecr.io/${APP}:bootstrap"

GH_REPO="${GH_REPO:-fireflyframework/fireflyframework-agentic}"
GH_REF="${GH_REF:-refs/heads/main}"

az account set --subscription "$SUB"

echo "==> Log Analytics workspace"
az monitor log-analytics workspace create \
  -g "$RG" -n "$LAW" -l "$LOC" --sku PerGB2018 --retention-time 30 -o none
LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LAW" --query primarySharedKey -o tsv)

echo "==> ACR"
az acr create -g "$RG" -n "$ACR" -l "$LOC" --sku Basic --admin-enabled false -o none

echo "==> Storage account + blob container"
az storage account create -g "$RG" -n "$SA" -l "$LOC" \
  --sku Standard_LRS --kind StorageV2 --https-only true --min-tls-version TLS1_2 \
  --allow-blob-public-access false -o none
SA_KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)
az storage container create --name "$BLOB_CONTAINER" --account-name "$SA" --account-key "$SA_KEY" --public-access off -o none

echo "==> Key Vault"
az keyvault create -g "$RG" -n "$KV" -l "$LOC" \
  --enable-rbac-authorization true --enable-purge-protection true -o none

echo "==> User-assigned managed identity"
az identity create -g "$RG" -n "$MI" -l "$LOC" -o none
MI_ID=$(az identity show -g "$RG" -n "$MI" --query id -o tsv)
MI_PRINCIPAL=$(az identity show -g "$RG" -n "$MI" --query principalId -o tsv)
MI_CLIENT=$(az identity show -g "$RG" -n "$MI" --query clientId -o tsv)

echo "==> Role assignments for MI"
ACR_ID=$(az acr show -g "$RG" -n "$ACR" --query id -o tsv)
SA_ID=$(az storage account show -g "$RG" -n "$SA" --query id -o tsv)
KV_ID=$(az keyvault show -g "$RG" -n "$KV" --query id -o tsv)

az role assignment create --assignee-object-id "$MI_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$ACR_ID" -o none || true
az role assignment create --assignee-object-id "$MI_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$SA_ID" -o none || true
az role assignment create --assignee-object-id "$MI_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" -o none || true

echo "==> Federated credential for GitHub Actions"
az identity federated-credential create -g "$RG" --identity-name "$MI" \
  --name "gh-${GH_REPO//\//-}-main" \
  --issuer "https://token.actions.githubusercontent.com" \
  --subject "repo:${GH_REPO}:ref:${GH_REF}" \
  --audiences "api://AzureADTokenExchange" -o none || true

echo "==> Container Apps environment"
az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOC" \
  --logs-workspace-id "$LAW_ID" --logs-workspace-key "$LAW_KEY" -o none

echo "==> Container App (bootstrap with placeholder image)"
if ! az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  az containerapp create -g "$RG" -n "$APP" \
    --environment "$ENV_NAME" \
    --image mcr.microsoft.com/k8se/quickstart:latest \
    --target-port 8000 --ingress external \
    --user-assigned "$MI_ID" \
    --registry-server "${ACR}.azurecr.io" --registry-identity "$MI_ID" \
    --min-replicas 0 --max-replicas 3 \
    --cpu 0.5 --memory 1.0Gi -o none
fi

echo
echo "Done. Next steps:"
echo "  1. Build & push the real image: docker buildx build --push -t ${IMAGE} ."
echo "  2. az containerapp update -g $RG -n $APP --image ${IMAGE}"
echo "  3. Configure EasyAuth (Entra ID provider) on $APP via portal or 'az containerapp auth' (requires app registration)."
echo
echo "Managed identity client id: $MI_CLIENT"
