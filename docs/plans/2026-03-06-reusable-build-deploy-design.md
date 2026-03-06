# Reusable Build And Deploy Workflow Design

## Context

`vps-services` currently provides a single reusable workflow, `deploy-service.yml`, that assumes one deployable service per repository:

- one root `Dockerfile`
- one `deploy/manifest.yml`
- one `deploy/compose.yml`

That works for repositories like `pomodoro`, but it does not map cleanly to `hoop`, which is a monorepo with multiple Dockerfiles and one shared VPS compose stack. Extending the manifest shape would add a new engineer-facing model to learn, which we want to avoid.

## Goals

- Support both single-repo apps and monorepos with reusable workflows.
- Keep deployment inputs explicit in workflow callers rather than adding a new manifest format.
- Let `hoop` build multiple images and deploy one shared compose stack.
- Keep database bootstrap simple: create databases if missing, no role creation/grant orchestration.

## Non-Goals

- Rebuilding a full deployment framework.
- Adding local GitHub Actions emulation or `act` support.
- Preserving the manifest-driven reusable workflow as the primary path for new repos.

## Options Considered

### 1. Extend the current manifest model for monorepos

This would keep one workflow but add monorepo-specific keys to the manifest. Rejected because it introduces a second deploy model that engineers would need to learn.

### 2. Keep one workflow and pass many path/service inputs

This is workable but the workflow would still mix validation, build, env assembly, and deployment into one contract. It reduces the root-path assumption, but it does not improve separation of concerns.

### 3. Split reusable concerns into build and deploy workflows

This separates image build from VPS deployment:

- `build-image.yml` handles checkout, GHCR login, metadata, build, and push.
- `deploy-compose.yml` handles compose sync, env writing, optional database creation, service rollout, and health checks.

Chosen because it fits both `pomodoro` and `hoop` cleanly without inventing a new manifest format.

## Proposed Architecture

### Reusable workflow 1: `build-image.yml`

Inputs:

- `image`
- `context`
- `dockerfile`

Behavior:

- check out the caller repository
- log in to GHCR
- build and push the image
- publish a SHA tag and a stable tag on the default branch

Outputs:

- resolved image tag

### Reusable workflow 2: `deploy-compose.yml`

Inputs:

- `deploy_dir`
- `compose_file`
- `services`
- `env_content`
- `health_retries` (optional)
- `health_interval` (optional)
- `bootstrap_databases` (optional)

Behavior:

- check out the caller repository
- copy the selected compose file to the VPS as `docker-compose.yml`
- write the caller-provided runtime `.env`
- create listed databases when missing
- run `docker compose pull <services>` and `docker compose up -d <services>`
- wait until requested services are running and healthy, or have no Docker healthcheck

## Repo Migration Shape

### `pomodoro`

- replace the current workflow with:
  - one `build-image` call
  - one `deploy-compose` call
- keep env assembly explicit in the repo workflow
- preserve the existing runtime variables and database bootstrap behavior

### `hoop`

- replace the current workflow with:
  - one build job for `api`
  - one build job for `web`
  - one deploy job for the shared compose stack
- keep deploy env assembly explicit in the repo workflow
- remove DB role bootstrap/grant logic and only create the database if it does not exist

## Error Handling

- missing compose file or Dockerfile fails immediately
- empty runtime env content fails immediately
- invalid database names fail before database creation
- deploy fails if any requested service never reaches running/healthy state
- deploy health checks inspect only the requested services

## Testing Strategy

- validate modified YAML files locally with `ruby -e "require 'yaml'; YAML.load_file(...)"`
- inspect diffs to confirm secret/variable parity with the prior workflows
- run final repo status and commit verification after edits

## Tradeoffs

- caller workflows become a bit more explicit because env assembly moves out of the reusable workflow
- in exchange, reusable workflows are smaller, clearer, and monorepo-safe

## Decision

Implement `build-image.yml` and `deploy-compose.yml` in `vps-services`, migrate `pomodoro` and `hoop` to them, and keep database bootstrap limited to creating missing databases.
