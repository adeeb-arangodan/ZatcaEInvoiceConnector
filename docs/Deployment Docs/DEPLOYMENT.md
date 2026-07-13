# Deployment Guide — Windows 10 (production)

This guide covers deploying this Django app as a standing production service on a
Windows 10 PC that also hosts another project. The two apps are kept isolated by
running on different ports (and, if desired, different Windows services), so
neither one needs to know about the other.

Two settings changes already made in this repo to support this:

- `ZatcaEInvoiceConnector/settings.py` now reads `SECRET_KEY`, `DEBUG`,
  `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS` from environment variables
  (falling back to the old insecure dev defaults if unset, so local `runserver`
  workflows are unaffected).
- `whitenoise` was added to `MIDDLEWARE` and `STATIC_ROOT` was set, so static
  files (admin CSS/JS, captcha images) can be served correctly without IIS.
- `requirements.txt` now includes `waitress` (a pure-Python production WSGI
  server that runs natively on Windows — `gunicorn` does not) and `whitenoise`.

## 1. Prerequisites on the target PC

- Python 3.12+ (matches Django 6.0's minimum) installed and on `PATH`.
- `openssl` on `PATH` — required by `organization/services.py` for device
  key/CSR generation. Git for Windows ships an `openssl.exe`; or install it
  standalone and add its folder to `PATH`.
- Git (optional, if pulling the repo directly) or just copy the project folder
  over.

Verify from `cmd.exe`:

```cmd
python --version
openssl version
```

## 2. Get the code onto the machine and set up the environment

```cmd
cd C:\Apps
git clone <repo-url> ZatcaEInvoiceConnector
cd ZatcaEInvoiceConnector

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Use a dedicated folder per app, e.g. `C:\Apps\ZatcaEInvoiceConnector` and
`C:\Apps\OtherProject`, each with its own virtual environment — keeps
dependency versions from the two projects from colliding.

## 3. Configure environment variables (`.env`)

Create `.env` in the project root (same folder as `manage.py`). This is loaded
automatically via `python-dotenv`. Do **not** commit this file.

```ini
# --- Django ---
DJANGO_SECRET_KEY=<generate a real one, see below>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<hostname-or-LAN-IP-of-this-PC>
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8001

# --- ZATCA connector ---
DEVICE_KEY_ENCRYPTION_KEY=<generate with the command below>
ZATCA_SERVER_URL=https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal
ZATCA_COMPLIANCE_API_ENDPOINT=/compliance
ZATCA_API_ACCEPT_VERSION=V2
ZATCA_API_TIMEOUT_SECONDS=30
ZATCA_COMPLIANCE_INVOICE_CHECK_API_ENDPOINT=/compliance/invoices/reporting/single
ZATCA_PRODUCTION_CSID_API_ENDPOINT=/production/csids
ZATCA_REPORTING_API_ENDPOINT=/invoices/reporting/single
ZATCA_CLEARANCE_API_ENDPOINT=/invoices/clearance/single
```

Generate the two secrets:

```cmd
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the first output in `DJANGO_SECRET_KEY`, the second in
`DEVICE_KEY_ENCRYPTION_KEY`. Store a backup of `DEVICE_KEY_ENCRYPTION_KEY`
somewhere safe outside the project folder — losing it makes every already-stored
device private key unrecoverable.

## 4. Database, static files, admin user

```cmd
.venv\Scripts\activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

`collectstatic` copies static assets into `STATIC_ROOT` (`staticfiles/`), which
`whitenoise` then serves directly from the WSGI app — no separate static file
server needed.

The database is SQLite (`db.sqlite3`), fine for this app's traffic profile.
Back it up regularly (see §8) — SQLite has no built-in replication.

## 5. Choosing a port (coexisting with the other project)

Pick a distinct port per app, e.g.:

| App                     | Port |
|--------------------------|------|
| ZatcaEInvoiceConnector   | 8001 |
| Other project            | 8002 |

Anything above 1024 and not already in use is fine. Check what's free before
committing to a number:

```cmd
netstat -ano | findstr :8001
```

No output means the port is free. If both apps eventually need to be reachable
under normal-looking URLs (no `:port` in the address) rather than raw ports,
put IIS or another reverse proxy in front of both and route by hostname or
path — see §7.

## 6. Running in production with Waitress

Don't use `manage.py runserver` in production — it's single-threaded and not
hardened. Use `waitress` instead, bound to the chosen port:

```cmd
.venv\Scripts\activate
waitress-serve --host=0.0.0.0 --port=8001 ZatcaEInvoiceConnector.wsgi:application
```

`--host=0.0.0.0` makes it reachable from other machines on the LAN; use
`--host=127.0.0.1` to restrict it to the local machine only.

### Running it as a Windows Service (so it survives reboots/logoffs)

Running the command above in a terminal only lasts until that terminal
closes. For a real production deployment, wrap it as a Windows Service using
[NSSM](https://nssm.cc/) (Non-Sucking Service Manager) — free, and the
standard way to run arbitrary Windows-native processes as services:

1. Download NSSM, extract, and note the path to `nssm.exe` (use the `win64`
   binary).
2. Install the service:

   ```cmd
   nssm install ZatcaEInvoiceConnector
   ```

   This opens a GUI. Set:
   - **Path**: `C:\Apps\ZatcaEInvoiceConnector\.venv\Scripts\waitress-serve.exe`
   - **Startup directory**: `C:\Apps\ZatcaEInvoiceConnector`
   - **Arguments**: `--host=0.0.0.0 --port=8001 ZatcaEInvoiceConnector.wsgi:application`
   - On the **Details** tab, set a friendly display name, e.g. "Zatca E-Invoice Connector".
   - On the **I/O** tab, optionally redirect stdout/stderr to a log file, e.g.
     `C:\Apps\ZatcaEInvoiceConnector\logs\service.log`.
3. Start it:

   ```cmd
   nssm start ZatcaEInvoiceConnector
   ```

Do the same for the other project with its own service name and port — each
service is independent, starts automatically on boot, and NSSM auto-restarts
it if the process crashes.

Useful NSSM commands:

```cmd
nssm status ZatcaEInvoiceConnector
nssm stop ZatcaEInvoiceConnector
nssm restart ZatcaEInvoiceConnector
nssm remove ZatcaEInvoiceConnector confirm
```

## 7. Firewall and (optional) reverse proxy / HTTPS

If only apps on the same PC (or same LAN, over plain HTTP) need to reach this
service, you're done after §6. To allow inbound access through Windows
Firewall:

```cmd
netsh advfirewall firewall add rule name="ZatcaEInvoiceConnector" dir=in action=allow protocol=TCP localport=8001
```

If this needs to be reachable over HTTPS with a real domain name (e.g.
external ERP systems submitting invoices over the internet), don't expose
Waitress directly — put a reverse proxy in front of it that terminates TLS:

- **IIS** with the **Application Request Routing (ARR)** + **URL Rewrite**
  modules can proxy `https://invoices.mycompany.local/` → `http://127.0.0.1:8001/`,
  and likewise route the other project's hostname/path to its own port. This
  also lets both apps share port 443 externally while staying on separate
  internal ports.
- Alternatively, a lightweight reverse proxy like **Caddy** (automatic HTTPS,
  simple config file) is easier to set up than IIS+ARR if you don't already
  have IIS in use.

Either way, once a reverse proxy is in front, set `DJANGO_ALLOWED_HOSTS` and
`DJANGO_CSRF_TRUSTED_ORIGINS` in `.env` to the public hostname (not just
`localhost`), and set the proxy to forward the `X-Forwarded-Proto` header if
terminating TLS there.

## 8. Backups and logs

- **Database**: copy `db.sqlite3` on a schedule (Task Scheduler + a script
  that stops the service, copies the file, restarts it — or use
  `sqlite3 db.sqlite3 ".backup backup.sqlite3"` which is safe to run live).
- **`.env`**: back up separately and securely — it contains the encryption
  key protecting every device's private key.
- **Logs**: if using NSSM's I/O redirection (§6), rotate `service.log`
  periodically (NSSM has built-in log rotation options in the **I/O** tab —
  "Rotate files" + "Restrict rotation to files bigger than").

## 9. Post-deploy checklist

- [ ] `.env` created with real `DJANGO_SECRET_KEY`, `DEVICE_KEY_ENCRYPTION_KEY`, `DJANGO_DEBUG=False`
- [ ] `DJANGO_ALLOWED_HOSTS` includes every hostname/IP this will be reached by
- [ ] `python manage.py migrate` run
- [ ] `python manage.py collectstatic --noinput` run
- [ ] Admin superuser created, can log into `/admin/`
- [ ] Waitress serving on the chosen port, distinct from the other project's port
- [ ] Windows Service installed via NSSM, starts on boot, auto-restarts on crash
- [ ] Firewall rule added if remote access is needed
- [ ] First organization created and activated via `/admin/`, first device
      registered, a test invoice submitted successfully
- [ ] Backup schedule in place for `db.sqlite3` and `.env`

## 10. Updating an existing deployment

For a PC that's already set up (has its own `.env` and `db.sqlite3`), pull
the update in place rather than re-cloning — `.env` and `db.sqlite3` are
both gitignored, so a pull never touches either one.

1. **Check for local drift before pulling.** If any settings were ever
   hand-edited directly on this PC (e.g. to match a change described here in
   `DEPLOYMENT.md` before it had actually landed in git yet), a plain pull
   can fail with "local changes would be overwritten by merge":

   ```cmd
   git status
   git diff ZatcaEInvoiceConnector\settings.py
   ```

   - No local modifications shown → skip to step 2.
   - Local modifications shown and they look like the same change that's
     about to come in from the pull → stash and drop it rather than
     reapplying a now-redundant diff:
     ```cmd
     git stash
     git pull origin master
     git stash drop
     ```
   - Local modifications include something *extra* not present upstream →
     use `git stash pop` instead and resolve the conflict by hand, keeping
     the extra bits.

2. **Pull the latest code:**
   ```cmd
   git pull origin master
   ```

3. **Reinstall dependencies** (in case `requirements.txt` changed):
   ```cmd
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Re-run migrate and collectstatic:**
   ```cmd
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

5. **Confirm `.env` still has everything the current `settings.py` expects**
   (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
   `DJANGO_CSRF_TRUSTED_ORIGINS`, `DEVICE_KEY_ENCRYPTION_KEY`, `ZATCA_*`) —
   a pull never adds or edits `.env` for you.

6. **Restart the Windows Service** — a `git pull` alone doesn't restart the
   running process:
   ```cmd
   nssm restart ZatcaEInvoiceConnector
   nssm status ZatcaEInvoiceConnector
   ```

7. **Smoke-test**: log into `/admin/` and confirm the app still comes up
   cleanly and reflects the expected new behavior (e.g. a new admin action
   or page) before considering the update done.
