# Changelog for `ny.vps`

## 1.3.1

- The onboarding guard also opens when Home Assistant has finished all steps: it no longer serves `/api/onboarding` and returns the exact 404 `404: Not Found`. Any other 404 stays closed.

## 1.3.0

- Extra hostnames per instance allowed only by administrator policy; private onboarding guard closed on error and permanent block of public administrator creation.
- `vpsctl ingress refresh` reconciles objects and republishes routes under lock, with no new generation or application restart; maintenance every five minutes and no reload if the configuration is unchanged.
- `stop_grace_period` accepted between 1 and 300 seconds and checked in the Docker runtime.

## 1.2.0

- Admission budgets configurable from inventory: `controller_budgets` and `controller_preview_instance_budget` (playbooks: `vps_budgets`, `vps_preview_instance_budget`). Defaults unchanged.

## 1.1.0

- Multiple routes per instance: primary name and `<prefix>.<primary name>`, each once; all probed before publication and for `http_status`. Protocol unchanged (version 1).

## 1.0.0

- Protocol version 1 request between application repositories and `vpsctl`.
- Platform roles: `host`, `ssh`, `firewall`, `docker`, `ingress`, `controller`.
- Application role `app` and `deploy_instance` module.
