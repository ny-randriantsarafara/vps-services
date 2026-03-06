# Inline Bootstrap Design

**Goal:** Remove the extra private-repo checkout from the reusable deploy workflow while preserving manifest-driven database bootstrap before service startup.

**Problem:** The current deploy workflow checks out `ny-randriantsarafara/vps-services` a second time during deploy so it can copy `scripts/ensure-postgres-databases.sh` to the VPS. In reusable-workflow context, that cross-repo checkout introduces an avoidable private-repo auth dependency and decouples the helper script revision from the workflow revision actually invoked by callers.

## Recommended Approach

Keep `bootstrap.databases` in caller manifests, including `pomodoro/deploy/manifest.yml`, but move the bootstrap logic directly into the existing remote deploy heredoc in `vps-services/.github/workflows/deploy-service.yml`.

The deploy job should:

1. Read `bootstrap.databases` from the caller manifest exactly as it does today.
2. SSH to the VPS without a second repository checkout.
3. Define small shell helpers inside the remote heredoc to validate database names, check for existence in `supabase-db`, and create missing databases.
4. Run those helpers only when `BOOTSTRAP_DATABASES` is non-empty, before `docker compose pull` and `docker compose up`.

## Why This Approach

- Removes the private cross-repo checkout entirely.
- Ensures the bootstrap logic always matches the exact reusable workflow revision the caller selected.
- Keeps bootstrap behavior centralized in the shared workflow instead of duplicating scripts across service repositories.
- Preserves the existing manifest contract for service repositories.

## Error Handling

- Invalid database names fail the deploy before service startup.
- `docker exec supabase-db ...` failures fail the deploy immediately.
- Existing databases are logged and skipped.
- Empty or missing `bootstrap.databases` leaves deploy behavior unchanged.

## Verification

- Validate the workflow YAML remains syntactically valid.
- Run shell syntax checks on any remaining bootstrap script files if they stay in the repo.
- Re-review the deploy workflow diff to confirm the second checkout and helper upload are fully removed.
