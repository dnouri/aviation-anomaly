# Aviation Anomaly Tracker - Deployment TODO

## Summary

Deploy the aviation anomaly tracker as a production web application on the existing Ubuntu 24.04 server (nv-network). The deployment uses a fully self-contained, immutable container architecture with automatic HTTPS.

**Target State:**
- Application accessible via HTTPS on custom domain with auto-renewing SSL
- Rootless Podman container running FastAPI backend + static frontend
- Caddy reverse proxy handling HTTPS termination
- Systemd user service for automatic container restart
- Container includes all data (H3 aggregations, incidents, PMTiles) - 695MB deployment
- Health checks for automatic failure detection and recovery

**Timeline:** Weekend deployment (24-48 hours)

**Key Constraints:**
- Server has 17GB free disk space (enough for 695MB data + containers)
- Must coexist with existing services on 356-day uptime server
- Rootless deployment (no privileged containers)

## Architecture Decisions Recap

1. **No segments deployment** - API doesn't need segments directory (only H3, incidents, PMTiles). Saves 31GB.
2. **Caddy over nginx** - Automatic HTTPS with Let's Encrypt, simpler config than nginx+certbot. Safe to replace (nginx only serves default page).
3. **Python 3.13 in container** - Self-contained, exact version match, no system Python dependencies.
4. **Container health checks** - Application-level `/health` endpoint detects broken states, not just crashes.
5. **Immutable containers** - Data baked into image for atomic updates and instant rollback.
6. **Moderate Makefile integration** - Make handles build/tag/push, scripts handle complex deployment logic.

---

## Phase 0: Pre-flight Checks

**Motivation:** Verify environment and prerequisites before making changes. Catch blockers early.

**Outcome:** Confirmed that local dev environment and server meet requirements.

### Tasks

- [x] **Verify local test suite passes**
  - Run `make test-unit` (non-integration tests)
  - 221 tests passed, 9 pre-existing failures (pipeline tests, not API serving)
  - Verified: API tests pass, failures don't block deployment

- [x] **Verify local data files present**
  - Checked `data/h3/` (211M), `data/incidents/` (68K), `data/tiles/pmtiles/` (398M)
  - Total size ~609MB within 695MB target
  - Verified: All H3 (R3-R7), incidents (6 dates), PMTiles (R3-R6) present

- [x] **Verify server connectivity and prerequisites**
  - SSH access: Both `root@nv-network` and `daniel@nv-network` working
  - Disk space: 17GB free (54% used, 38GB total)
  - Docker 26.1.4 installed, systemd 255 available
  - Verified: Can execute commands as both root and daniel

- [x] **Verify domain and DNS configuration**
  - Domain: anomaly.danielnouri.org
  - DNS A record: 135.181.148.109 (matches server IP)
  - Verified: DNS propagated and resolves correctly

---

## Phase 1: Application Code Changes

**Motivation:** Add health endpoint and container configuration. Test these locally before building containers.

**Outcome:** Application has health checking capability and container build definition.

### Tasks

- [x] **Add health endpoint to FastAPI application**
  - Enhanced existing `/health` endpoint in `aviation_anomaly/api.py`
  - Verifies: DuckDB connection (SELECT 1), data file queryable (COUNT on h3_incidents_r3.parquet)
  - Returns JSON: `{"status": "healthy/unhealthy", "checks": {"duckdb": "ok", "data_files": "ok (N cells)"}}`
  - Returns 200 on success, 503 on failure with error details
  - Uses JSONResponse for proper JSON serialization

- [x] **Create Containerfile for Podman build**
  - Base: `FROM python:3.13-slim` with curl and ca-certificates
  - Install uv 0.4.30 for dependency management
  - Copy: pyproject.toml, config.toml, aviation_anomaly/, static/, data (H3, incidents, PMTiles)
  - Install deps: `uv pip install --system -e .`
  - HEALTHCHECK: 30s interval, queries `/health` endpoint
  - CMD: `uvicorn aviation_anomaly.api:app --host 0.0.0.0 --port 8000`

- [x] **Create .containerignore file**
  - Excludes: .git/, __pycache__/, .venv/, data/segments/ (31GB!), test caches, IDE files
  - Includes: Only production essentials (code, data, config)
  - Verified: Segments excluded, saves 31GB from image

- [x] **Test health endpoint locally**
  - Fixed missing `app` module-level export (added `app = create_app()`)
  - Fixed missing `config` parameter in health check
  - Tested: Returns 200 OK with `{"status":"healthy","checks":{"duckdb":"ok","data_files":"ok (7953 cells)"}}`
  - Verified: DuckDB connection and data file querying work correctly

---

## Phase 2: Local Container Build & Test

**Motivation:** Build and validate container on dev machine before touching production server. Catch build issues early.

**Outcome:** Working container image ready for deployment.

### Tasks

- [x] **Build container image locally**
  - Built with Docker format: `podman build --format docker -t aviation-anomaly:test -f Containerfile .`
  - Final size: 1.17 GB (python:3.13-slim base 130MB + dependencies 220MB + data 609MB + overhead)
  - Fixed critical config loading bug: Changed `Config()` → `Config.from_file("config.toml")` in 3 locations
  - Fixed config.toml temp_directory for container portability: `/tmp/duckdb` instead of dev path
  - Verified: Image builds successfully with all data files included

- [x] **Test container runs and serves application**
  - Ran container: `podman run -d --name test-aviation -p 8002:8000 aviation-anomaly:test`
  - Container started successfully and remained running
  - Uvicorn started on port 8000 inside container
  - Verified: Application accessible from inside container

- [x] **Test container health check**
  - HEALTHCHECK status: **healthy** (`podman inspect` confirms)
  - Health endpoint returns: `{"status": "healthy", "checks": {"duckdb": "ok", "data_files": "ok (7953 cells)"}}`
  - Config.toml loaded correctly (would fail health check otherwise)
  - DuckDB connection and data file access verified

- [x] **Test API endpoints in container**
  - Tested H3 summary endpoint: Returns real data from Parquet files
  - Tested with cell 589971894782918655: Correct JSON response with h3_res, incidents, segments
  - Tested 404 behavior: Proper error JSON for invalid cells
  - Static HTML: Aviation Anomaly Tracker interface loads correctly
  - Verified: All endpoints functional

---

## Phase 3: Server Preparation

**Motivation:** Install and configure server-side dependencies. Prepare environment for rootless container deployment.

**Outcome:** Server has Podman installed with rootless configuration and systemd user services enabled.

### Tasks

- [ ] **Install Podman on server**
  - SSH as root: `ssh root@nv-network`
  - Install: `apt update && apt install -y podman`
  - Verify: `podman --version` returns 3.4.4 or newer
  - Test rootless: As daniel user, `podman run --rm hello-world`

- [ ] **Configure systemd lingering for daniel user**
  - As root: `loginctl enable-linger daniel`
  - Verify: `loginctl show-user daniel | grep Linger` shows `Linger=yes`
  - Purpose: Allows daniel's systemd user services to run without active SSH session

- [ ] **Verify user namespaces configured**
  - Check: `cat /etc/subuid | grep daniel` shows `daniel:100000:65536`
  - Check: `cat /etc/subgid | grep daniel` shows `daniel:100000:65536`
  - Verify: Already configured (confirmed in reconnaissance)

- [ ] **Create deployment directory structure**
  - As daniel: `mkdir -p ~/aviation-anomaly-deploy/{containers,logs,scripts}`
  - Purpose: Organized location for deployment artifacts
  - Verify: `ls -la ~/aviation-anomaly-deploy`

- [ ] **Optional: Clean up unused Docker images to free space**
  - Check current usage: `docker images` and `docker ps -a`
  - If no containers running and images unused: `docker system prune -a`
  - Potential space savings: ~9GB
  - Verify: `df -h` shows increased free space (skip if Docker images needed)

---

## Phase 4: Deployment Automation

**Motivation:** Create reusable scripts and Makefile targets for repeatable deployments and updates.

**Outcome:** `make deploy` command handles full deployment workflow.

### Tasks

- [ ] **Create build script: scripts/deploy/build_container.sh**
  - Generate git-based tag: `GIT_SHA=$(git rev-parse --short HEAD)`
  - Build with multiple tags: `:$GIT_SHA`, `:latest`, `:$(date +%Y%m%d)`
  - Save image to tarball: `podman save -o aviation-anomaly-$GIT_SHA.tar`
  - Print image size and tags
  - Verify: Script is executable, runs successfully

- [ ] **Create upload script: scripts/deploy/upload_container.sh**
  - Accept container tarball path as argument
  - SCP tarball to server: `scp $tarball daniel@nv-network:~/aviation-anomaly-deploy/containers/`
  - SSH and load image: `podman load -i ~/aviation-anomaly-deploy/containers/$tarball`
  - Verify: Script uploads and loads successfully

- [ ] **Create deployment script: scripts/deploy/deploy_container.sh**
  - Accept image tag as argument
  - Stop existing container if running: `podman stop aviation-anomaly || true`
  - Remove old container: `podman rm aviation-anomaly || true`
  - Start new container with correct ports and name
  - Tag as `:production` for systemd service to reference
  - Verify: Script successfully replaces running container

- [ ] **Create systemd service generator: scripts/deploy/generate_systemd_service.sh**
  - Generate `~/.config/systemd/user/aviation-anomaly.service`
  - Service should use `podman run` with correct parameters
  - Restart policy: `Restart=always`, `RestartSec=10s`
  - Health check: Systemd monitors Podman's health status
  - Verify: Generated service file is valid systemd syntax

- [ ] **Add Makefile deployment targets**
  - `build-container`: Calls `scripts/deploy/build_container.sh`
  - `upload-container`: Calls upload script with latest tarball
  - `deploy-container`: Calls deployment script
  - `deploy`: Orchestrates full workflow (build → upload → deploy)
  - `deploy-logs`: Show container logs via `podman logs -f`
  - Verify: `make build-container` works locally

---

## Phase 5: Reverse Proxy Setup

**Motivation:** Install and configure Caddy for automatic HTTPS. Replace nginx which only serves default page.

**Outcome:** Caddy running with automatic Let's Encrypt SSL, proxying to container on port 8000.

### Tasks

- [ ] **Backup current nginx configuration**
  - As root: `tar -czf /root/nginx-backup-$(date +%Y%m%d).tar.gz /etc/nginx`
  - Verify: Backup file exists in `/root/`
  - Note: Can restore with nginx if needed, though current config is default only

- [ ] **Install Caddy**
  - As root: Follow official Caddy install for Ubuntu: `https://caddyserver.com/docs/install#debian-ubuntu-raspbian`
  - Commands: Add Caddy GPG key, add apt source, `apt install caddy`
  - Verify: `caddy version` shows v2.6+

- [ ] **Stop and disable nginx**
  - As root: `systemctl stop nginx`
  - Disable: `systemctl disable nginx`
  - Verify: `systemctl status nginx` shows inactive, `ss -tlnp | grep :80` shows port 80 free

- [ ] **Create Caddyfile configuration**
  - Location: `/etc/caddy/Caddyfile`
  - Configuration:
    ```
    yourdomain.com {
        reverse_proxy localhost:8000
        encode gzip
        log {
            output file /var/log/caddy/aviation-anomaly.log
        }
    }
    ```
  - Replace `yourdomain.com` with actual domain
  - Verify: `caddy validate --config /etc/caddy/Caddyfile` passes

- [ ] **Start Caddy and test HTTPS**
  - As root: `systemctl enable --now caddy`
  - Caddy automatically obtains Let's Encrypt certificate
  - Verify: `systemctl status caddy` shows active
  - Verify: `curl -I https://yourdomain.com` returns 200 (will be 502 until container runs)

- [ ] **Verify automatic HTTPS redirect**
  - Test: `curl -I http://yourdomain.com` should redirect to HTTPS
  - Verify: Response includes `Location: https://`

---

## Phase 6: Production Deployment

**Motivation:** Deploy container to server and configure as systemd service for automatic restart and management.

**Outcome:** Aviation anomaly application running in production, accessible via HTTPS, managed by systemd.

### Tasks

- [ ] **Build and upload container to server**
  - Locally: `make build-container`
  - Locally: `make upload-container`
  - Verify: SSH to server, `podman images` shows aviation-anomaly image

- [ ] **Generate and install systemd user service**
  - On server as daniel: Run `scripts/deploy/generate_systemd_service.sh`
  - Reload systemd: `systemctl --user daemon-reload`
  - Verify: `systemctl --user status aviation-anomaly` shows loaded (not running yet)

- [ ] **Start container via systemd**
  - As daniel: `systemctl --user enable --now aviation-anomaly`
  - Wait 30 seconds for startup and health checks
  - Verify: `systemctl --user status aviation-anomaly` shows active (running)
  - Verify: `podman ps` shows container running
  - Verify: `curl http://localhost:8000/health` returns healthy

- [ ] **Configure firewall if needed**
  - Check: `ufw status` (if enabled)
  - If UFW active: `ufw allow 80/tcp && ufw allow 443/tcp`
  - Verify: Ports 80 and 443 accessible from internet

---

## Phase 7: Verification & Monitoring

**Motivation:** Comprehensive testing of production deployment. Verify all functionality works end-to-end.

**Outcome:** Confirmed working production deployment with monitoring in place.

### Tasks

- [ ] **Test public HTTPS access**
  - Browser: `https://yourdomain.com`
  - Verify: Map loads, HTTPS certificate valid (green lock), no console errors
  - Verify: Can interact with map (zoom, pan, click cells)

- [ ] **Test API endpoints via HTTPS**
  - H3 aggregation: `curl https://yourdomain.com/api/h3/incidents?resolution=3`
  - Verify: Returns valid JSON with incident counts
  - Drill-down: Click a cell with incidents, verify incident list appears
  - Verify: ADS-B Exchange links work (open one in new tab)

- [ ] **Test container health checks**
  - Check Podman health: `podman inspect aviation-anomaly | grep -A 10 Health`
  - Verify: Status "healthy", no failures
  - Check systemd: `systemctl --user status aviation-anomaly`
  - Verify: "Healthy" in status output

- [ ] **Test automatic restart on failure**
  - Simulate failure: `podman kill aviation-anomaly`
  - Wait 15 seconds
  - Verify: `podman ps` shows container restarted
  - Verify: Application accessible again at `https://yourdomain.com`

- [ ] **Verify logs and monitoring**
  - Container logs: `podman logs aviation-anomaly | tail -50`
  - Caddy logs: `tail -50 /var/log/caddy/aviation-anomaly.log`
  - Systemd journal: `journalctl --user -u aviation-anomaly -n 50`
  - Verify: No errors, healthy requests logged

- [ ] **Document deployment for future updates**
  - Note container image tag deployed: `podman images | grep aviation-anomaly`
  - Note date deployed and git commit SHA
  - Create quick reference: "To update: `make deploy` from local machine"
  - Verify: Documentation clear for future self

- [ ] **Celebrate successful deployment! 🎉**
  - Share link with colleagues/friends
  - Monitor access logs for first visitors
  - Consider: Post on relevant forums/communities for feedback

---

## Update Workflow (Future Reference)

When data updates are available:

1. **Local:** Run pipeline to generate new data
2. **Local:** Verify tests pass with new data
3. **Local:** `make build-container` (rebuilds with new data)
4. **Local:** `make deploy` (uploads and restarts on server)
5. **Server:** Verify health checks pass
6. **Rollback if needed:** `systemctl --user restart aviation-anomaly` with previous image tag

Old container images remain available for instant rollback: `podman images aviation-anomaly`.

---

## Appendix: Key Commands Reference

### Local Development
- Build container: `podman build -t aviation-anomaly:test -f Containerfile .`
- Test container: `podman run --rm -p 8000:8000 aviation-anomaly:test`
- Run tests: `make test-quick`

### Server Management (as daniel@nv-network)
- Container status: `podman ps`
- Service status: `systemctl --user status aviation-anomaly`
- View logs: `podman logs -f aviation-anomaly`
- Restart service: `systemctl --user restart aviation-anomaly`
- Stop service: `systemctl --user stop aviation-anomaly`

### Deployment Workflow
- Full deploy: `make deploy` (local machine)
- Build only: `make build-container`
- View deployment logs: `make deploy-logs` (connects to server logs)

### Caddy Management (as root@nv-network)
- Reload config: `systemctl reload caddy`
- View status: `systemctl status caddy`
- Check certificates: `ls -la /var/lib/caddy/.local/share/caddy/certificates/`
- Force cert renewal: `caddy renew --config /etc/caddy/Caddyfile`
