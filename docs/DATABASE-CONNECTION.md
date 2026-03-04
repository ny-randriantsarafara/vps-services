# Database Connection Guide

Connect to the remote PostgreSQL database via SSH tunnel.

## Prerequisites

- SSH access to the VPS (configured in `~/.ssh/config` or via key)
- Your `.env` file with `VPS_HOST` and `VPS_USER` configured
- A PostgreSQL client (psql, pgAdmin, DBeaver, etc.)

## Connection Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Host** | `localhost` | Always localhost (through tunnel) |
| **Port** | `5432` | Session mode (long connections) |
| **Port** | `6543` | Transaction mode (short queries) |
| **Database** | `postgres` | From `POSTGRES_DB` |
| **Username** | `postgres.{TENANT_ID}` | Pooler requires tenant suffix |
| **Password** | See `.env` | From `POSTGRES_PASSWORD` |

**Important:** The username must include the tenant ID suffix (e.g., `postgres.bgj3WDTa`). The tenant ID is defined in `POOLER_TENANT_ID` in your `.env` file. Without this suffix, the Supavisor pooler will reject the connection.

## Method 1: CLI with `make tunnel`

Open a tunnel in one terminal:

```bash
make tunnel
```

Connect with psql in another terminal:

```bash
PGPASSWORD='your-password' psql -h localhost -p 5432 -U postgres.bgj3WDTa -d postgres
```

## Method 2: pgAdmin Native SSH Tunnel

### General Tab

| Field | Value |
|-------|-------|
| Name | `VPS Supabase` (any name) |

### Connection Tab

| Field | Value |
|-------|-------|
| Host name/address | `localhost` |
| Port | `5432` |
| Maintenance database | `postgres` |
| Username | `postgres.{POOLER_TENANT_ID}` |
| Password | Value from `POSTGRES_PASSWORD` |

### SSH Tunnel Tab

| Field | Value |
|-------|-------|
| Use SSH tunneling | Yes |
| Tunnel host | Value from `VPS_HOST` |
| Tunnel port | `22` |
| Username | Value from `VPS_USER` |
| Authentication | Identity file |
| Identity file | Path to your SSH private key |

## Port Selection

| Port | Mode | Best For |
|------|------|----------|
| `5432` | Session | Migrations, admin tasks, long-running queries |
| `6543` | Transaction | API requests, short queries, connection pooling |

## Troubleshooting

### "server closed the connection unexpectedly"

**Cause:** Missing tenant ID in username.

**Fix:** Use `postgres.{POOLER_TENANT_ID}` instead of just `postgres`.

### "User not found" in pooler logs

**Cause:** Same as above - the Supavisor pooler requires the tenant ID suffix.

**Fix:** Check `POOLER_TENANT_ID` in `.env` and append it to your username.

### Connection timeout

**Cause:** SSH tunnel not established or VPS unreachable.

**Fix:**
1. Verify SSH access: `ssh $VPS_USER@$VPS_HOST`
2. Check if containers are running: `docker ps | grep -E 'postgres|pooler'`

### Check pooler logs

```bash
ssh $VPS_USER@$VPS_HOST "docker logs supabase-pooler --tail 50"
```

### Check PostgreSQL status

```bash
ssh $VPS_USER@$VPS_HOST "docker exec supabase-db pg_isready -h localhost -p 5432"
```
