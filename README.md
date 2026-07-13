# Realistic DEV Deployment - Notes App

A minimal but real end-to-end scenario: a static frontend, a Python Function
App API, PostgreSQL for metadata, Blob Storage for file attachments, and
Key Vault for the DB secret - deployed via two GitHub Actions pipelines.

```
frontend/     Static Web App (HTML/JS)
api/          Function App (Python 3.9, v2 model)
db/           Postgres schema
.github/      CI/CD workflows
```

## 1. One-time Azure setup

Run these against your existing DEV resource group (adjust names to match
what's actually in your resource group).

**Create the notes table:**
```bash
psql "host=postgres-flexible-dev.postgres.database.azure.com dbname=postgres user=dbadmin sslmode=require" \
  -f db/schema.sql
```

**Store the DB connection string in Key Vault** (the API reads it from here,
not from an app setting):
```bash
az keyvault secret set \
  --vault-name key-vault-dev \
  --name db-connection-string \
  --value "host=postgres-flexible-dev.postgres.database.azure.com dbname=postgres user=dbadmin password=<pwd> sslmode=require"
```

**Enable Managed Identity on the Function App and grant it access:**
```bash
az functionapp identity assign --name function-app-dev --resource-group <rg-name>

# Get the principal ID from the output above, then:
az role assignment create --assignee <principal-id> --role "Key Vault Secrets User" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg-name>/providers/Microsoft.KeyVault/vaults/key-vault-dev

az role assignment create --assignee <principal-id> --role "Storage Blob Data Contributor" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg-name>/providers/Microsoft.Storage/storageAccounts/<storage-account-name>
```

**Set the Function App's application settings** (non-secret config only):
```bash
az functionapp config appsettings set --name function-app-dev --resource-group <rg-name> --settings \
  KEY_VAULT_URL="https://key-vault-dev.vault.azure.net/" \
  STORAGE_ACCOUNT_URL="https://<storage-account-name>.blob.core.windows.net" \
  BLOB_CONTAINER="attachments"
```

**Link the Function App to the Static Web App** (so `/api/*` calls from the
frontend route through automatically, no CORS needed):
```bash
az staticwebapp backends link \
  --name <static-web-app-name> \
  --resource-group <rg-name> \
  --backend-resource-id /subscriptions/<sub-id>/resourceGroups/<rg-name>/providers/Microsoft.Web/sites/function-app-dev \
  --backend-region <region>
```

## 2. GitHub setup

**For the Static Web App pipeline:**
- Get the deployment token: `az staticwebapp secrets list --name <static-web-app-name>`
- Add it as a repo secret: `AZURE_STATIC_WEB_APPS_API_TOKEN_DEV`

**For the Function App pipeline (OIDC, no stored secret):**
```bash
az ad app create --display-name "github-actions-function-app-dev"
# note the appId (client ID) from output

az ad app federated-credential create --id <appId> --parameters '{
  "name": "github-dev-branch",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<org>/<repo>:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'

az role assignment create --assignee <appId> --role Contributor \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg-name>
```
Add three repo secrets: `AZURE_CLIENT_ID` (the appId), `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`.

## 3. Test it end to end

1. Push to `main` - both workflows fire (only the one touching changed
   paths actually redeploys, thanks to the `paths:` filters).
2. Open the Static Web App URL.
3. Create a note with a small file attached.
4. Confirm: the note appears (proves Postgres write + read), and clicking
   "Download attachment" pulls the file back (proves Blob Storage), and
   none of this required a connection string in your repo or app settings
   (proves Key Vault + Managed Identity).
5. Check Application Insights (`monitoring-dev`) for the request traces.

## Notes on what's simplified vs. a real PROD setup

- HTTP routes are anonymous - fine for this DEV smoke test, not for PROD.
- No input validation beyond "title is required" - add real validation
  before this becomes anything client-facing.
- The Postgres connection still uses username/password (pulled from Key
  Vault) rather than Azure AD auth to Postgres - a reasonable next step if
  you want to drop passwords entirely.
- Static Web App `paths:` filters mean each pipeline only runs when its
  own folder changes - useful once you're iterating on frontend and API
  independently.
