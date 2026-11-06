# Deploy and recover Alcove

The Compose package runs one Django service with Gunicorn and WhiteNoise. The
image installs locked runtime dependencies and collects the checked-in browser
assets at build time. The server runs as a non-root user and applies migrations
before accepting traffic. The application uses one SQLite file on a host bind
mount, which survives container replacement.

## Check the host

Before deploying, confirm the server's OS and CPU architecture, available RAM and
disk space, a current Docker Engine with the Compose plugin, and access to the
image and Python package registries for the initial build. Choose a writable,
persistent local filesystem for SQLite and its journal files. Confirm the
container UID/GID can write there, accounting for user namespaces or host
security policy. Use a separate protected backup destination with enough space
for retained copies and a restore rehearsal. The data directory and backup
staging directory must support hard links for atomic publication. Stage backups
on local disk before transferring retained copies to other media.

Choose a private access route from the intended phone and computer, such as a
private LAN or VPN with HTTPS. Confirm DNS, certificate trust on both devices,
the proxy's ability to reach the host loopback port, and the host firewall rules.
These are requirements to check on the deployment host.

## Start from a clean checkout

On a typical Linux host, create the storage and backup directories as the
operator. This example uses the operator's numeric UID and GID for the
container, so the same user can manage backup files on the host.

```sh
storage="$HOME/alcove-storage"
install -d -m 700 "$storage" "$storage/data" "$storage/backups"
(umask 077 && cp .env.example .env)
printf 'Data path %s, UID %s, GID %s\n' "$storage/data" "$(id -u)" "$(id -g)"
openssl rand -hex 48
```

Set `ALCOVE_DATA_DIR` to the printed absolute data path, `ALCOVE_UID` and
`ALCOVE_GID` to the printed IDs, and `ALCOVE_SECRET_KEY` to the generated value.
Keep the secret stable across restarts. Set `ALCOVE_ALLOWED_HOSTS` to the
hostname clients use, without a scheme or port. Keep `.env` private and store its
recovery copy separately from the database backup. Use a non-root operator UID.

The app publishes HTTP only on host loopback. Place an HTTPS reverse proxy on the
host and keep direct access to the app port limited to trusted local processes.
Keep `ALCOVE_TRUST_PROXY_HTTPS=1` only when the proxy preserves the original
`Host` and strips incoming `X-Forwarded-Proto` before setting it from the client
connection. This lets Django enforce same-origin CSRF and issue secure session
cookies. [Django proxy settings](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header)

For a disposable local HTTPS rehearsal with Caddy on the host, use
`ALCOVE_ALLOWED_HOSTS=localhost` and the following Caddyfile. Trust Caddy's local
CA in the test browser and open `https://localhost:8443`. Use the equivalent
private hostname and trusted TLS configuration for the actual server.
[Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
[Caddy local HTTPS](https://caddyserver.com/docs/automatic-https#local-https)

```caddyfile
https://localhost:8443 {
    tls internal
    reverse_proxy 127.0.0.1:8000
}
```

Validate configuration, build, and start the service. Provision the owner
interactively after migrations complete. Repeating provisioning with the same
username preserves the password and Collection.

```sh
docker compose config --quiet
docker compose build --pull app
docker compose up -d --wait app
docker compose exec app python manage.py provision_owner reader
curl -fsS http://127.0.0.1:8000/healthz
```

If you change `ALCOVE_PORT`, use that port for the proxy and the loopback probe.
`GET /healthz` responds with `200` and `ok` when SQLite can read the Collection
table, or `503` and `unavailable` on a database error. It exposes no Collection
data and needs no session. Use `docker compose ps` and
`docker compose logs --tail=100 app` to diagnose startup or health failures.
To change the owner's password, run
`docker compose exec app python manage.py changepassword reader`.

## Back up the database

Use a unique filename for each snapshot. The backup can run while the service
is up. SQLite's backup API copies a consistent committed database into a single
file, including committed changes that may still be in a WAL. The command checks
the snapshot before publishing it and refuses an existing destination. If the
source remains locked, the command fails and leaves the destination absent.
Retry after the operation holding the lock finishes.
[SQLite online backup API](https://www.sqlite.org/backup.html)

```sh
backup="alcove-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
docker compose run --rm --no-deps -v "$storage/backups:/backups" app \
  python manage.py backup_database "/backups/$backup"
```

Retain a protected copy on separate storage. This database snapshot contains
private Notes, password hashes, and sessions. The Django secret and other
deployment settings are stored separately. Portable Collection exports exclude
deployment settings, credentials, and sessions.

## Rehearse restart and isolated recovery

1. Sign in over HTTPS and capture a distinct Note in the editor. Record its
   detail URL and read the same UUID at `/api/v1/notes/{uuid}/` while signed in.
   Use the [API guide](api.md) to capture a second Note through the JSON API.
   Open its HTML detail page and check both Notes' content.
2. Create the backup above. Run `docker compose restart app`, then
   `docker compose up -d --wait app`. Sign in and read both Notes again over
   HTML and JSON.
3. Create a separate data directory and env file for recovery. Set the recovery
   file's `ALCOVE_DATA_DIR` to the printed path, `ALCOVE_PORT` to an unused port
   such as `8001`, and `ALCOVE_SECRET_KEY` to a fresh random value for the drill.
   The original database stays attached to its own deployment. Keep these
   variables in the env file so shell exports do not override them.

   ```sh
   install -d -m 700 "$storage/recovery"
   printf 'Recovery data path %s\n' "$storage/recovery"
   recovery_env="$(mktemp)"
   cp .env "$recovery_env"
   ```

4. Restore into the new data directory **before** starting that deployment.
   The restore command requires the target database and its SQLite sidecars to
   be absent. It validates the snapshot and leaves the target absent on error.
   Use the app image from the backup's version or a compatible newer version.

   ```sh
   docker compose --env-file "$recovery_env" -p alcove-recovery run --rm --no-deps \
     -v "$storage/backups:/backups:ro" app \
     python manage.py restore_database "/backups/$backup"
   docker compose --env-file "$recovery_env" -p alcove-recovery up -d --wait app
   ```

5. Route a separate HTTPS origin to the recovery port, for example another
   Caddy site at `https://localhost:8444` proxying to `127.0.0.1:8001`. Use a
   fresh browser profile, sign in with the backed-up owner's password, and
   verify the original Note IDs and content through both interfaces. Stop
   the recovery deployment with
   `docker compose --env-file "$recovery_env" -p alcove-recovery down`.

The repository also has a clean local rehearsal without Docker. With the
[development test prerequisites](../README.md#check-the-application) and OpenSSL
installed, run `uv run pytest tests/test_deployment.py`. It starts the production
launcher over loopback HTTPS and uses temporary deployment and recovery
directories with real SQLite.

## Upgrade or recover the main service

Record the current source revision and set a distinct `ALCOVE_IMAGE_TAG` per
release to retain the previous image for rollback. Stop the app with
`docker compose stop app` before taking the pre-upgrade backup, then keep that
backup outside the data directory. Check out the target release, update the image
tag, build with `docker compose build --pull app`, and start it with
`docker compose up -d --wait app`. Startup applies the new migrations. Check
health, sign in, and verify that a previously captured Note can still be read.

To recover or roll back, stop the service. Preserve the old database and its
sidecars together in their existing directory. Set `ALCOVE_DATA_DIR` to a new,
empty directory, select the image version that matches the backup, and run the
restore command against that directory before bringing the service up. Keep the
deployment secret and HTTPS settings available separately. After startup, sign
in again and verify the Notes before retiring the previous storage directory.
