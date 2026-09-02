# Operations

## Weekly rhythm

- Merge dependency update PRs or record why deferred.
- Review error logs in Log Analytics for top failures.
- Run `make check` on latest `main`.

## Monthly rhythm

- **Clean clone check:** fresh machine or container, follow README only, run `make install && make check`.
- **Atlas backup restore:** operator-owned — restore into scratch environment and verify logbook reads.
- Raise one automated check (coverage floor, lint rule, type strictness) by one notch.

## Rollback

1. Identify the previous GHCR image tag from the last successful CD run (`ghcr.io/arshad98333/hafizal-ghidha:<short-sha>`).
2. GitHub Actions → CD workflow → Run workflow with the previous image tag (or update the Container Apps Job image manually).
3. Re-run the failed stage: `az containerapp job start --name <job> --resource-group <rg> --args "<stage>" "--wave" "<n>"`.

## Health probes (Container Apps Job)

```bash
# Liveness — config valid
python -m cold_chain.runner health

# Readiness — MongoDB reachable
python -m cold_chain.runner ready
```

## Secrets rotation (Key Vault)

When `mongodbKeyVaultSecretUri` is set in `infra/main.json`, rotate the Mongo credential in Atlas, update the Key Vault secret version, and restart the job — no redeploy required.

## Data retention

- `live_logs` collection: 30-day TTL (Atlas).
- Synthetic training records: MongoDB `generation_log` per wave; export via `scripts/export_wave.py`.
