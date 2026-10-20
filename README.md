# Textile Production Intelligence

A local-first web application for recording and reviewing textile production
operations: orders, batches, production targets and actual output, downtime,
rework and rejection, with KPIs calculated from validated source records.

> **Status: first implementation, not yet run on Windows.** The code was
> written and partly verified in an environment without Django installed. See
> [Verification status](#verification-status) before relying on it. **Do this
> first:** run `scripts\check.bat` after setup and fix anything it reports.

All demonstration data is **synthetic** (references start with `SYN-`) and is
not actual factory data, a benchmark, or evidence of performance.

## Features (implemented)

- **Orders** and **batches** with unique IDs, status (Planned / In progress /
  Completed / Cancelled, with enforced transitions), search and filters.
- **Production records**: target (optional) and actual output per record, unit,
  optional period label; per-record achievement and variance.
- **Downtime**: start/end timestamps (timezone-aware, cross-midnight safe),
  derived duration, categories, overlap warnings.
- **Quality records**: rework and rejection as separate event-level records.
- **Dashboard** and **Reports** using one shared KPI engine, with filters
  (dates, order, batch, statuses, category, type) and **CSV export** (summary
  and downtime events) with spreadsheet formula-injection protection.
- Explicit **"Not available"** states (zero/missing target, no denominator),
  distinct from zero and from "no records".
- Remaining order quantity with over-production flagging (provisional
  definition, see `docs/DOMAIN_RULES.md`).
- Protected history (PROTECT foreign keys), POST-only state changes, CSRF.
- Optional synthetic demo-data loader; SQLite backup/restore scripts.

Not implemented (by specification or because undefined): rework/rejection
*rates*, shifts, OEE/efficiency, authentication/roles, charts (tables and KPI
cards are used instead), machine integration, AI/ML.

## Technology

Python 3.12, Django 5.2 LTS, SQLite, Django templates with a self-contained
CSS file (no CDN, no external fonts or scripts), minimal vanilla JavaScript,
pytest + pytest-django, Ruff.

**Deviation from the stack document:** Bootstrap 5 and Chart.js are *not*
bundled. They could not be downloaded in the build environment, and the
interface works fully without them using `static/css/app.css` (palette from
`app_theme.md`). Charts were optional in the specification.

## Windows setup (Command Prompt)

Prerequisites: Python 3.12 from python.org (tick "Add python.exe to PATH" and
keep the `py` launcher), and internet access for the one-time install.

```
cd textile-production-intelligence
scripts\setup.bat
scripts\check.bat
scripts\run.bat
```

Then open <http://127.0.0.1:8000/>. Equivalent manual commands:

```
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Optional: `python manage.py createsuperuser` to use the admin site at `/admin/`
(for example to add units of measure).

### Demo data (optional, explicit)

```
python manage.py load_demo_data               load synthetic SYN- orders
python manage.py load_demo_data --remove      preview what would be removed
python manage.py load_demo_data --remove --yes    remove only SYN- data
```

It never runs automatically, is idempotent (existing `SYN-` orders are left
untouched), and never touches non-`SYN-` records.

### Configuration

Environment variables (see `.env.example`; set with `set NAME=value` in CMD):
`DJANGO_TIME_ZONE` (default `Asia/Kolkata`), `DJANGO_DB_PATH`, `DJANGO_DEBUG`,
`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`. Debug defaults on for local use.
If `DJANGO_DEBUG=0` a secret key is required.

## Using the application

1. **Production Orders -> Add Order** (ID, product, quantity, unit).
2. **Production Batches -> Add Batch** and pick the order.
3. **Production Records -> Add**: target (leave blank if none), actual output,
   unit; batch is optional but must belong to the order.
4. **Downtime -> Add**: start and end date/time. **Quality Records -> Add**:
   rework or rejection quantity.
5. Review **Dashboard** and **Reports**; use "View records" links to trace any
   figure to its records. Edit records to correct them; summaries recalculate.

Orders and batches can be deleted only when nothing is linked to them.

## Tests and quality checks

```
python -m pytest
ruff check .
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
```
(`scripts\check.bat` runs the first four.) Tests use an isolated test database
and deterministic synthetic data; expected values are hand-calculated.

## Backup and restore

See `docs/BACKUP_AND_RESTORE.md` (`scripts\backup_db.py`, `scripts\restore_db.py`).

## Security and deployment

For **trusted local use only**: there is no login and no role-based access. Do
not expose it to an untrusted network. The Django development server is not a
production server. Production data must never be committed (`.gitignore`
excludes databases, backups and `.env`).

## Verification status

Performed in the build environment (no Django, pytest or Ruff installed, no
network):

- 95 test cases for the framework-independent services (KPIs, remaining
  quantity, downtime, quality, status rules, unit compatibility, CSV safety)
  **were executed and passed** using a small stand-in runner, *not* real pytest.
- Every Python file compiles; a static pass found no lines over 100
  characters or unused imports; template tags are balanced and every
  referenced URL name exists.
- Backup and restore scripts were run successfully against a scratch SQLite DB.

**Not executed (needs your Windows machine):** installing dependencies,
`migrate`, `manage.py check`, `makemigrations --check` (the initial migration
is hand-written and could differ from what Django generates; if the check
reports changes, run `python manage.py makemigrations` and keep the result),
the 130 Django tests (models, forms, views, reports, demo data, project checks),
Ruff, server startup, and any browser check of layout/accessibility. Treat
these as **unverified** until `scripts\check.bat` passes.

## Known limitations

- Single-user local operation; no authentication or concurrency control.
- No units conversion; SQLite sums use floating point internally, results are
  normalised to 3 decimals (safe within the 14-digit field limit).
- Downtime totals are loaded in Python per request; fine for modest volumes
  (not measured at scale).
- Rework/rejection rates, shifts and efficiency KPIs are intentionally absent
  (undefined). See `docs/DOMAIN_RULES.md` for assumptions to confirm.
- No browser/accessibility audit has been performed.

## Licensing

Project: MIT (`LICENSE`, copyright Vipin T K - change if you prefer another
licence). Django is BSD-3-Clause; `tzdata` Apache-2.0; pytest, pytest-django
and Ruff are MIT. Check licences again before redistributing any bundled
frontend assets (none are bundled).

## Publishing to GitHub (account vipintk2807)

Target: `https://github.com/vipintk2807/textile-production-intelligence`. Run
in CMD inside the project folder. Never paste passwords or tokens anywhere.

1. Check the identity and any existing remote:
   ```
   git config user.name
   git config user.email
   git remote -v
   ```
2. Initialise and set a repository-local identity (does not change global):
   ```
   git init -b main
   git config user.name "Vipin T K"
   git config user.email "YOUR-GITHUB-EMAIL"
   ```
3. Confirm the SSH alias exists and reaches the right account:
   ```
   type %USERPROFILE%\.ssh\config
   ssh -T git@github-vipintk2807
   ```
   The greeting must say `Hi vipintk2807!`. If the alias is missing or shows
   another account, stop and fix it first (or use HTTPS).
4. Review what will be committed (no databases, backups, `.env`, planning docs):
   ```
   git status
   git add .
   git status
   ```
5. Commit, then add the remote and verify before pushing:
   ```
   git commit -m "Initial implementation"
   git remote add origin git@github-vipintk2807:vipintk2807/textile-production-intelligence.git
   git remote -v
   git branch --show-current
   ```
6. Create the empty repository on github.com first (no README), then:
   ```
   git push -u origin main
   ```
