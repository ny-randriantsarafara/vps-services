"""Frozen caddy_configuration from vps-services b2c8644 (pre-RTMPS). Reference only."""

from pathlib import Path

REQUEST_LOG_DIRECTORY = Path("/var/log/caddy")


def request_logging(routes):
    names, logs = {}, {}
    for route in routes:
        if "application" not in route or "environment" not in route:
            continue
        application, environment = route["application"], route["environment"]
        name = application + "-" + environment
        names[route["hostname"]] = name
        logs[name] = {
            "include": ["http.log.access." + name],
            "writer": {
                "output": "file",
                "filename": str(REQUEST_LOG_DIRECTORY / "vps-http.json"),
                "mode": "0600",
                "dir_mode": "0700",
                "roll_size_mb": 10,
                "roll_keep": 2,
                "roll_keep_days": 1,
            },
            "encoder": {
                "format": "append",
                "fields": {"application": application, "environment": environment},
                "wrap": {
                    "format": "filter",
                    "wrap": {"format": "json"},
                    "fields": {
                        key: {"filter": "delete"}
                        for key in (
                            "request",
                            "resp_headers",
                            "user_id",
                            "error",
                            "err_id",
                            "err_trace",
                        )
                    },
                },
            },
        }
    if not logs:
        return {}, {}
    logs["default"] = {"exclude": ["http.log.access"]}
    return {"logs": logs}, {"logger_names": names, "skip_unmapped_hosts": True}


def caddy_configuration(admin_socket, routes, guards=None, private_paths=None):
    guards = guards or {}
    private_paths = private_paths or {}
    logging, access = request_logging(routes)
    handlers = []
    denied = {"handler": "static_response", "status_code": 403, "body": "private setup required"}
    for route in routes:
        hostname = route["hostname"]
        if private_paths.get(hostname):
            handlers.append(
                {
                    "match": [{"host": [hostname], "path": private_paths[hostname]}],
                    "handle": [denied],
                    "terminal": True,
                }
            )
        if hostname in guards:
            handlers.append(
                {
                    "match": [{"host": [hostname], "path": ["/api/onboarding/users*"]}],
                    "handle": [denied],
                    "terminal": True,
                }
            )
        handler = {"handler": "reverse_proxy", "upstreams": [{"dial": route["upstream"]}]}
        if hostname in guards and not guards[hostname]:
            handler = denied
        handlers.append({"match": [{"host": [hostname]}], "handle": [handler], "terminal": True})
    neutral = {"handle": [{"handler": "static_response", "status_code": 404}], "terminal": True}
    return {
        **({"logging": logging} if logging else {}),
        "admin": {"listen": "unix/" + admin_socket},
        "apps": {
            "http": {
                "metrics": {},
                "servers": {
                    "platform": {
                        "listen": [":443"],
                        **({"logs": access} if access else {}),
                        "routes": [*handlers, neutral],
                    }
                },
            }
        },
    }
