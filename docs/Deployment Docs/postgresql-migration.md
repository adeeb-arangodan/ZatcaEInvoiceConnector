# Migrating from SQLite to PostgreSQL

This app currently uses SQLite (`db.sqlite3`). This doc covers moving to
PostgreSQL, and why it matters for a database that ZATCA requires you to
retain for at least six years.

Nothing in the live project has been changed. Two new sibling files were
added for you to review and manually swap in when ready:

- `ZatcaEInvoiceConnector/settings.postgresql.py` — identical to
  `settings.py` except the `DATABASES` block now points at PostgreSQL.
- `requirements.postgresql.txt` — identical to `requirements.txt` plus the
  `psycopg[binary]` driver.

## Why Postgres over SQLite for this app specifically

**Row-level locking on the ICV/PIH chain.** `hashing.get_icv_and_pih_atomically()`
takes `Organization.select_for_update()` to atomically bump the invoice
counter and read the previous invoice hash (see CLAUDE.md's "ICV/PIH chain"
section). Under SQLite, the entire database file is locked for any write,
regardless of which table/row it touches — so if you ever run multiple
organizations concurrently, a write for Org A can momentarily block a write
for Org B even though they don't share any data. Postgres locks only the
specific row being updated, so unrelated organizations' invoice submissions
never block each other.

**Durability and recovery tooling.** SQLite is a single file; if it's
corrupted (disk fault, bad shutdown mid-write, corrupted copy) there's no
built-in point-in-time recovery — you're restoring from whatever your last
full-file backup happened to be. Postgres has a write-ahead log (WAL) that,
combined with `pg_basebackup`, lets you restore to any point in time (e.g.
"restore to 2 minutes before the disk issue"), not just to the last nightly
snapshot. For a database you're contractually required to keep intact for
six years, that's a meaningful difference.

**Growth over six years.** SQLite performs fine up to a certain size, but it
was never designed as a heavily-written, multi-year-growing production
store — no user/role-based access control, no native replication, limited
tooling for online schema changes or partitioning as the `invoices` table
grows into the millions of rows. Postgres handles all of this.

## 1. Install PostgreSQL on the Windows PC

Download the Windows installer from postgresql.org (EDB's installer is the
common choice) and run it. During setup:

- Set a password for the `postgres` superuser — record it somewhere safe.
- Default port `5432` is fine (change it only if it conflicts with something
  else already running).
- Let it install pgAdmin (optional GUI) if you want a visual tool for
  inspecting the database later.

Verify it's running:

```cmd
sc query postgresql-x64-17
```

(service name varies by installed version — check `services.msc` if unsure).

## 2. Create the database and app user

Open `psql` (Start Menu → PostgreSQL → SQL Shell) or use pgAdmin, then:

```sql
CREATE DATABASE zatca_einvoice;
CREATE USER zatca_app WITH PASSWORD 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON DATABASE zatca_einvoice TO zatca_app;
ALTER DATABASE zatca_einvoice OWNER TO zatca_app;
```

Use a dedicated, non-superuser account (`zatca_app`) for the app rather than
connecting as `postgres` — standard least-privilege practice.

## 3. Add the new env vars to `.env`

```ini
DB_NAME=zatca_einvoice
DB_USER=zatca_app
DB_PASSWORD=choose-a-strong-password
DB_HOST=localhost
DB_PORT=5432
```

(`localhost`/`5432` assumes Postgres runs on the same PC as the app, as
discussed. If it ever moves to a separate DB server, only `DB_HOST` needs to
change.)

## 4. Swap in the new settings and requirements

Once you're ready to cut over:

```cmd
.venv\Scripts\activate
copy ZatcaEInvoiceConnector\settings.postgresql.py ZatcaEInvoiceConnector\settings.py
copy requirements.postgresql.txt requirements.txt
pip install -r requirements.txt
python manage.py migrate
```

`migrate` on a fresh Postgres database creates all tables from scratch —
fine if you haven't gone live yet. If you already have real data sitting in
`db.sqlite3` that needs to carry over, see the next section instead of
running a plain `migrate`.

## 5. Migrating existing data out of `db.sqlite3` (if any)

If `db.sqlite3` already has real organizations/devices/invoices in it:

```cmd
:: 1. While still pointed at SQLite (before swapping settings.py):
python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.Permission > data_dump.json

:: 2. Swap in Postgres settings/requirements (step 4 above), then:
python manage.py migrate
python manage.py loaddata data_dump.json
```

For very large datasets, `dumpdata`/`loaddata` can be slow — `pgloader`
(with its SQLite source support) is a faster alternative for bulk migration,
but `dumpdata`/`loaddata` is sufficient for typical volumes and doesn't
require installing anything extra.

**Back up `db.sqlite3` itself before doing this** (just copy the file
somewhere) — keep it as a cold archive even after migrating, in case you
need to cross-check the migration.

## 6. Backup strategy for the 6-year retention requirement

A single nightly file copy is not enough for a legally-mandated 6-year
retention window — disks fail, backups get overwritten, and a single
corrupted backup file loses everything before it. Set up:

**Nightly full backups**, kept for a rolling window (e.g. 30 days) plus
monthly archives kept for the full 6+ years:

```cmd
pg_dump -U zatca_app -h localhost -F c zatca_einvoice > backup_%date:~-4,4%%date:~-10,2%%date:~-7,2%.dump
```

Schedule via Task Scheduler. Store backups on a **different physical disk**
than the live database — a backup on the same disk doesn't protect against
disk failure.

**WAL archiving**, for point-in-time recovery between full backups (so a
mid-day failure doesn't lose that day's invoices). Configure
`archive_mode = on` and `archive_command` in `postgresql.conf` to copy WAL
segments to a separate location as they're generated.

**Off-site/offline copy.** At minimum, periodically copy backups to a
location physically separate from this PC (network share, external drive
rotated off-site, or cloud storage) — a fire, theft, or ransomware incident
that takes out this PC should not also take out the only backup copy.

**Restore drills.** Periodically actually restore a backup to a scratch
database and confirm the data is intact and the app can read it — an
untested backup is not a verified backup.

**Retention of the retention itself.** Track which backups correspond to
which time periods so that, six-plus years from now, you can demonstrate to
ZATCA (or reconstruct) any invoice from that window on request — don't rely
purely on "we have backups somewhere," have an inventory.
