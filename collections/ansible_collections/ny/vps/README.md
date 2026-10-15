# Collection `ny.vps`

Single-VPS platform and application deployment contract.

| Item | Role |
| --- | --- |
| `ny.vps.host` | Debian 13, non-root administrator, security updates, bounded journal |
| `ny.vps.ssh` | SSH hardening validated with `sshd -t` |
| `ny.vps.firewall` | IPv4/IPv6 `INPUT` and `DOCKER-USER` rules, restored at boot |
| `ny.vps.docker` | Docker Engine and Compose from the signed APT repo, pinned versions |
| `ny.vps.ingress` | Caddy on the host, administration via Unix socket |
| `ny.vps.controller` | `vpsctl` command, admission policy, deploy accounts |
| `ny.vps.app` | Role for application repos: render Compose and call the controller |
| `ny.vps.deploy_instance` | Module that sends a protocol version 1 request |

The application contract is described in `docs/APP-CONTRACT.md` of the `vps-services` repository.
