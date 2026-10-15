# Home Assistant on the VPS

Authorized goal: Container instance on `vps-d9d9aca9.vps.ovh.net`, exact domain
`home-assistant.nyhasinavalona.com`, private personal repository and hub guide.

## Constraints

- Keep existing my-media instances, neighbor DNS, three submodules, and data.
- No public administrator onboarding: initial SSH tunnel, guard closed on error.
- No Tapo/SmartThings integration claimed connected without proof or subscribed plan.
- Deploy via `ny.vps.app`; official image by digest, isolated network, loopback only.

## Execution

- [ ] Platform: red tests then exact per-instance name permissions, graceful stop,
  administrator-driven onboarding guard, and ingress refresh under lock.
  Verify out-of-scope refusals, closed state on error, persistent protection of
  administrator creation, limits, and `make check`.
- [ ] Application: create standalone repository, Ansible deployment, pinned image,
  persistent config, initial tunnel, and targeted backup/restore.
  Deploy after platform review; check TLS, public 403, private onboarding,
  limits, restart and persistence, then my-media state.
- [ ] Hub: private repository, hub documentation reference.
  Publish the private repository then verify visibility
  and revision. Report latest human actions without inventing an account.
