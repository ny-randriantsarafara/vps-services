# Multiple routes, `apps` domain, and `my-media` accounts

Date: 11 October 2026. Status: approved; requested by `my-media` CI/CD (spec `docs/superpowers/specs/2026-10-11-cicd-design.md` in the `my-media` repository).

## Need

The Media publishes two names per instance: the site and Directus. Draft preview reads the session cookie set by Directus from the site. That cookie must cover both names without covering other instances: a preview runs unreviewed code and must never receive the production cookie.

## Decision

- An instance publishes its primary name `<label>.<domain>` and secondary names `<prefix>.<label>.<domain>`, where `<prefix>` is a label `[a-z][a-z0-9]{0,31}`. Each name at most once, at most 16 routes.
- Two instances have distinct labels: their name sets are disjoint by construction, with no reserved-name list.
- A cookie `Domain=<label>.<domain>` covers the site and its secondary names, but no other instance.
- All instance routes are probed on loopback before publication. `http_status` is `ready` only if all respond publicly.
- Domain: `apps.nyhasinavalona.com`. Cloudflare wildcard `*.apps` as A/AAAA, no proxy: it covers multiple levels, and Caddy obtains a certificate per name.
- Accounts: `my-media-nonprod` (`staging`, `preview`) and `my-media-prod` (`prod`), each with a dedicated ed25519 key. Private keys are in `my-media` GitHub environments.

## Rejected

- `<label>-<suffix>` (`my-media-pr-42-cms`). The only common parent of site and CMS would be the whole domain: the production cookie would leak to previews. Suffixes would also need to be reserved in application names to avoid collisions.
- One instance per service: the site would be separate from its database, and a preview would use two slots.
