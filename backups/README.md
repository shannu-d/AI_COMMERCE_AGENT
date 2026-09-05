# Database backups

**This directory is git-ignored and must stay that way.** A dump of this database
contains the `users` table (argon2id password digests) and `auth_tokens` (live
bearer tokens). It is a credential store even though it holds no key file, and
committing one would publish every account on this deployment.

## Why this exists

The live PostgreSQL on this machine is a **throwaway cluster unpacked into the
Windows temp directory** — there is no Docker and no installed PostgreSQL here
(`docs/implementation-status.md` §11). Its data directory is:

```
C:\Users\shanm\AppData\Local\Temp\claude\L--AI-COMMERCE\
    c9c515ce-3414-4757-af30-69f5c61c91c2\scratchpad\pg\
```

A disk cleanup or a temp sweep deletes it, and with it 17 orders, the merchant's
catalogue edits, the audit log and every account. These dumps are the copy that
survives that.

## What is in a dump

Everything: the 23 tables, the seeded catalogue plus the merchant's own additions
(53 products / 219 SKUs / 24 categories), 17 orders with their approvals,
payments and 134 audit events, and 3 accounts.

Two formats of the same database, taken together:

| File | Format | Restore with |
| --- | --- | --- |
| `ai_commerce-<stamp>.dump` | PostgreSQL custom, compressed | `pg_restore` |
| `ai_commerce-<stamp>.sql` | Plain SQL, `--no-owner --no-privileges` | `psql -f` |

The plain SQL one is readable and greppable and will restore into any PostgreSQL
16; the custom one is smaller and restores selectively. Keep both.

`ai_commerce_test` is **not** backed up. It is rebuilt from the migrations by the
test suite on demand, so a copy of it would only go stale.

## Taking a backup

`pg_dump` lives in the throwaway cluster's `bin`, so put that on `PATH` first:

```bash
export PATH="/c/Users/shanm/AppData/Local/Temp/claude/L--AI-COMMERCE/c9c515ce-3414-4757-af30-69f5c61c91c2/scratchpad/pg/pgsql/bin:$PATH"
STAMP=$(date +%Y%m%d-%H%M)

pg_dump -h 127.0.0.1 -U ai_commerce -d ai_commerce -Fc \
        -f "/l/AI_COMMERCE/backups/ai_commerce-$STAMP.dump"
pg_dump -h 127.0.0.1 -U ai_commerce -d ai_commerce --no-owner --no-privileges \
        -f "/l/AI_COMMERCE/backups/ai_commerce-$STAMP.sql"
```

Use `127.0.0.1`, never `localhost` — the same trap the runbook warns about for
`TEST_DATABASE_URL`.

## Restoring

Into an empty database, from the custom-format dump:

```bash
createdb -h 127.0.0.1 -U ai_commerce ai_commerce
pg_restore -h 127.0.0.1 -U ai_commerce -d ai_commerce \
           --no-owner --no-privileges backups/ai_commerce-<stamp>.dump
```

Or from the plain SQL:

```bash
psql -h 127.0.0.1 -U ai_commerce -d ai_commerce -f backups/ai_commerce-<stamp>.sql
```

**Do not run `alembic upgrade head` afterwards.** The dump already carries the
schema *and* the `alembic_version` row (`0006`), so the migrations have nothing
to do; running them against a restored database is how you find out whether your
migrations are idempotent, at the worst possible moment.

## If the cluster itself is gone

The dumps restore the data; they do not restore PostgreSQL. Rebuilding the
throwaway cluster is the procedure in `docs/implementation-status.md` §11 —
unpack the official PostgreSQL 16.4 Windows binary archive into a directory,
`initdb`, `pg_ctl start`, `createdb`, then restore as above. The binaries and
their 324 MB source zip currently live beside the data directory in temp, so if
you want a rebuild to be possible offline, copy `pgsql/` out of temp too (967 MB)
before the sweep takes it.

## Verification

A backup nobody has restored is a hypothesis. The 2026-09-05 dumps were checked
by restoring the custom-format file into a scratch database and comparing row
counts against the live one — products 53, variants 219, orders 17, payments 7,
audit events 134, sessions 66, users 3, and the 17 orders that resolve to
`demo@easybuy.test` through the session join. Every count matched; the scratch
database was then dropped.

Re-verify the same way after any restore you actually depend on.
