# platform/seed — install-time custom resources (D7)

Lambda code backing the `Seed` stack (`infra/seed.yaml`). Packaged by SAM via the
stack's `CodeUri: ../platform/seed/`.

| File | Backs | Does |
|------|-------|------|
| `seed_handler.py` | `SeederFunction` | Creates the bootstrap Cognito admin (password in Secrets Manager); reference-data seeding extension point. |
| `spa_deploy_handler.py` | `SpaDeployerFunction` | Uploads the built SPA + writes runtime `config.json` (apiEndpoint / userPoolId / userPoolClientId). |
| `cfn.py` | both | Minimal CloudFormation custom-resource response helper. |
| `spa/` | `spa_deploy_handler` | Built SPA bundle. **Populated at deploy time** from `frontend/dist/` (git-ignored, only `.gitkeep` is tracked). |

## Deploy-time prep (before `sam deploy`)
```bash
cd frontend && npm install && npm run build   # -> frontend/dist/
rm -rf platform/seed/spa && mkdir -p platform/seed/spa
cp -R frontend/dist/. platform/seed/spa/
```
SAM then bundles `platform/seed/` (including `spa/`) into both seed Lambdas.
