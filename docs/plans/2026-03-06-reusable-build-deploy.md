# Reusable Build And Deploy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single manifest-driven reusable deploy workflow with separate reusable build and deploy workflows, then migrate `pomodoro` and `hoop` to the new contract.

**Architecture:** `vps-services` will expose one workflow for image builds and one for compose-based VPS deploys. Application repositories will own their validation commands and runtime env assembly, then call the reusable workflows with explicit inputs.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, SSH, Docker Compose, shell, YAML

---

### Task 1: Document The Approved Refactor

**Files:**
- Create: `docs/plans/2026-03-06-reusable-build-deploy-design.md`
- Create: `docs/plans/2026-03-06-reusable-build-deploy.md`

**Step 1: Write the design and plan documents**

Include:

- the reason the manifest approach does not scale to `hoop`
- the split between reusable build and reusable deploy workflows
- the migration shape for `pomodoro` and `hoop`

**Step 2: Verify the files exist**

Run: `ls docs/plans/2026-03-06-reusable-build-deploy-design.md docs/plans/2026-03-06-reusable-build-deploy.md`
Expected: both files listed

**Step 3: Commit**

```bash
git add docs/plans/2026-03-06-reusable-build-deploy-design.md docs/plans/2026-03-06-reusable-build-deploy.md
git commit -m "docs: add reusable build and deploy design"
```

### Task 2: Add Reusable Build And Deploy Workflows In `vps-services`

**Files:**
- Create: `.github/workflows/build-image.yml`
- Create: `.github/workflows/deploy-compose.yml`
- Modify: `.github/workflows/deploy-service.yml`

**Step 1: Write the failing verification command**

Run:

```bash
ruby -e "require 'yaml'; %w[
  .github/workflows/build-image.yml
  .github/workflows/deploy-compose.yml
].each { |path| YAML.load_file(path) }"
```

Expected: fail because the new workflow files do not exist yet

**Step 2: Write minimal reusable workflows**

Add:

- `build-image.yml` with `workflow_call` inputs for image, context, dockerfile
- `deploy-compose.yml` with `workflow_call` inputs for deploy dir, compose file, services, env content, and optional DB bootstrap

Keep `deploy-service.yml` as a deprecated compatibility wrapper or explicit legacy path if practical; do not expand its contract further.

**Step 3: Verify the YAML parses**

Run:

```bash
ruby -e "require 'yaml'; %w[
  .github/workflows/build-image.yml
  .github/workflows/deploy-compose.yml
  .github/workflows/deploy-service.yml
].each { |path| YAML.load_file(path) }"
```

Expected: no output, exit 0

**Step 4: Commit**

```bash
git add .github/workflows/build-image.yml .github/workflows/deploy-compose.yml .github/workflows/deploy-service.yml
git commit -m "feat: add reusable build and deploy workflows"
```

### Task 3: Migrate `pomodoro` To The New Workflow Pair

**Files:**
- Modify: `/Users/nrandriantsarafara/Works/sandbox/pomodoro/.github/workflows/deploy.yml`

**Step 1: Write the failing verification command**

Run:

```bash
ruby -e "require 'yaml'; YAML.load_file('/Users/nrandriantsarafara/Works/sandbox/pomodoro/.github/workflows/deploy.yml')"
```

Expected: pass before edits, then use diff review to confirm the workflow still covers lint, test, build, deploy, env assembly, and DB bootstrap after migration

**Step 2: Write minimal workflow migration**

Replace the inline build/deploy logic with:

- local validate job
- reusable `build-image` job
- reusable `deploy-compose` job

Preserve the current env values and `pomodoro` database bootstrap.

**Step 3: Verify the YAML parses**

Run:

```bash
ruby -e "require 'yaml'; YAML.load_file('/Users/nrandriantsarafara/Works/sandbox/pomodoro/.github/workflows/deploy.yml')"
```

Expected: no output, exit 0

**Step 4: Commit**

```bash
git -C /Users/nrandriantsarafara/Works/sandbox/pomodoro add .github/workflows/deploy.yml
git -C /Users/nrandriantsarafara/Works/sandbox/pomodoro commit -m "feat: migrate deploy to reusable build and deploy workflows"
```

### Task 4: Migrate `hoop` To The New Workflow Pair

**Files:**
- Modify: `/Users/nrandriantsarafara/Works/sandbox/hoop/.github/workflows/deploy.yml`

**Step 1: Write the failing verification command**

Run:

```bash
ruby -e "require 'yaml'; YAML.load_file('/Users/nrandriantsarafara/Works/sandbox/hoop/.github/workflows/deploy.yml')"
```

Expected: pass before edits, then use diff review to confirm the workflow still covers skip logic, dual image builds, shared-stack deploy, env assembly, and database creation

**Step 2: Write minimal workflow migration**

Replace inline image builds and VPS deploy logic with:

- existing skip-check job
- reusable build job for `api`
- reusable build job for `web`
- reusable deploy job for the shared stack

Simplify database bootstrap to create the database if missing only. Do not recreate role or grant logic.

**Step 3: Verify the YAML parses**

Run:

```bash
ruby -e "require 'yaml'; YAML.load_file('/Users/nrandriantsarafara/Works/sandbox/hoop/.github/workflows/deploy.yml')"
```

Expected: no output, exit 0

**Step 4: Commit**

```bash
git -C /Users/nrandriantsarafara/Works/sandbox/hoop add .github/workflows/deploy.yml
git -C /Users/nrandriantsarafara/Works/sandbox/hoop commit -m "feat: migrate deploy to reusable workflows"
```

### Task 5: Final Verification Across Repos

**Files:**
- Verify: `.github/workflows/build-image.yml`
- Verify: `.github/workflows/deploy-compose.yml`
- Verify: `/Users/nrandriantsarafara/Works/sandbox/pomodoro/.github/workflows/deploy.yml`
- Verify: `/Users/nrandriantsarafara/Works/sandbox/hoop/.github/workflows/deploy.yml`

**Step 1: Run full YAML verification**

Run:

```bash
ruby -e "require 'yaml'; %w[
  /Users/nrandriantsarafara/Works/sandbox/vps-services/.github/workflows/build-image.yml
  /Users/nrandriantsarafara/Works/sandbox/vps-services/.github/workflows/deploy-compose.yml
  /Users/nrandriantsarafara/Works/sandbox/vps-services/.github/workflows/deploy-service.yml
  /Users/nrandriantsarafara/Works/sandbox/pomodoro/.github/workflows/deploy.yml
  /Users/nrandriantsarafara/Works/sandbox/hoop/.github/workflows/deploy.yml
].each { |path| YAML.load_file(path) }"
```

Expected: no output, exit 0

**Step 2: Review diffs**

Run:

```bash
git -C /Users/nrandriantsarafara/Works/sandbox/vps-services diff --stat
git -C /Users/nrandriantsarafara/Works/sandbox/pomodoro diff --stat
git -C /Users/nrandriantsarafara/Works/sandbox/hoop diff --stat
```

Expected: only the intended workflow/doc changes

**Step 3: Commit any remaining verification-safe changes**

```bash
git -C /Users/nrandriantsarafara/Works/sandbox/vps-services add -A
git -C /Users/nrandriantsarafara/Works/sandbox/vps-services commit -m "chore: finalize reusable workflow split"
git -C /Users/nrandriantsarafara/Works/sandbox/pomodoro add -A
git -C /Users/nrandriantsarafara/Works/sandbox/pomodoro commit -m "chore: finalize deploy workflow migration"
git -C /Users/nrandriantsarafara/Works/sandbox/hoop add -A
git -C /Users/nrandriantsarafara/Works/sandbox/hoop commit -m "chore: finalize hoop deploy workflow migration"
```
