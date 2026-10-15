# CI/CD

## This repository: validation only

`.github/workflows/validate.yml` runs on push, pull request, and manual trigger. It has no VPS secrets, connects to no server, and provisions nothing.

| Step | Command |
| --- | --- |
| Tools | `make setup`: `.venv` and `requirements-dev.lock`, installed with `--require-hashes` |
| Gates | `make check` |

`make check` runs `scripts/check.sh`:

1. `ruff check` and `ruff format --check`;
2. all unit tests (`python -m unittest discover -s tests`);
3. `ansible-lint --offline` on the production profile;
4. `ansible-playbook --syntax-check` for `bootstrap`, `platform`, `register-app`, and the example playbook;
5. build of the `ny.vps` collection;
6. `git diff --check` on all tracked files.

Actions are pinned by full SHA (`actions/checkout` v5.1.0, `actions/setup-python` v6.3.0), with `contents: read` and without keeping the checkout token. Python tool versions are fixed in `requirements-dev.txt`, with hashes in `requirements-dev.lock`:

```bash
uv pip compile requirements-dev.txt --python-version 3.13 --generate-hashes --output-file requirements-dev.lock
```

Local Docker test (`make integration`) is not run in CI: it creates containers and runs only on demand.

The platform is provisioned from the operator machine (`make platform TARGET=...`), never on push.

## Application repositories

An application deploys from its own repository: manually from a workstation, or via its CI. In both cases it goes through its playbook and the `ny.vps.app` role (see [APP-CONTRACT](APP-CONTRACT.md)). Any GitHub automation follows these rules:

- One SSH deploy account per use: nonprod (staging and previews) and production, separate. No `docker` group or general sudo; only `vpsctl request`.
- Private key and server host key in restricted GitHub environment secrets; verified `known_hosts`, never `StrictHostKeyChecking=no`.
- No secrets for PRs from forks. A privileged workflow must not run code from an unreviewed PR.
- Images built in CI, published, then sent **by digest**. No build on the VPS.
- Increasing `release_generation`, for example `github.run_id` or a delivery counter. GitHub `concurrency` per application and PR helps order jobs; it does not replace the VPS lock or generation check.
- On PR close, `operation=destroy` with a generation higher than the last delivery.
- The `ny.vps` collection is installed at a reviewed release SHA; each repository picks up its updates independently.

Model approved 11/10/2026 and applied by `my-media`:

- previews on non-draft PRs in the repository, destroyed on close;
- staging after green CI on the main branch;
- production via approved manual action, from digests validated in staging.

Application-side spec: `docs/superpowers/specs/2026-10-11-cicd-design.md` in the `my-media` repository.

`home-assistant` has a single production instance and no staging. Its CI delivers it after green checks on every push to `main`, with the `github-actions@home-assistant-prod` key held in the `production` GitHub environment, limited to `main`. It is the only key of `home-assistant-prod`: no workstation can deliver it.

This platform contains no workflow that rebuilds or redeploys all applications.
