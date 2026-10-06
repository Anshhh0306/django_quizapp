# QuizHub

A Django site for running class tests. Teachers build a test from a CSV or Excel file, share one link, and follow it live. Students open the link, sign in with their college email, and take it.

## What it does

- **Accounts**: students register with an `@srmist.edu.in` address and confirm it by email. Teachers register the same way and wait for a superadmin to approve them.
- **Tests**: a teacher uploads questions, picks the ones to use, sets a seat limit and an optional class list, and shares the link. A test is either *scheduled* (the teacher starts it, with a fixed time) or *open* (anytime, no timer).
- **Live control**: the teacher sees who is in the lobby and who is working, can freeze a seat, give extra time, and look at results.
- **Anti-cheat**: the server keeps the clock and locks a test to one browser. Leaving the exam window counts as a strike, and the third submits the test.
- **Security**: two-factor sign-in is required for teachers and superadmins. Repeated wrong passwords lock the account for a while.

## Run it on your computer

You need Python and PostgreSQL (https://www.postgresql.org/download/) with an empty database, for example `CREATE DATABASE quizhub;` in psql.

```
git clone https://github.com/Anshhh0306/django_quizapp.git
cd django_quizapp
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Make a file called `.env` next to `manage.py` with your database address (a password with symbols must be written percent-encoded: `@` becomes `%40`):

```
DATABASE_URL=postgres://postgres:YOUR_PASSWORD@localhost:5432/quizhub
TEST_DATABASE_URL=postgres://postgres:YOUR_PASSWORD@localhost:5432/quizhub
```

Then:

```
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open http://127.0.0.1:8000/. Without a mail password, the emails (verification links, resets) are printed in the terminal instead of being sent.

## Settings

Settings come from environment variables or a file called `.env`. `.env.example` lists them all; the three that only a real server needs are switched off. Copy the lines you need. On a real server, `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS` are required or the site refuses to start (see "On a real server" below). Never commit `.env`: it holds passwords.

## Database

PostgreSQL only. `DATABASE_URL` (for example `postgres://USER:PASSWORD@HOST:5432/DATABASE`) names the database, and the site refuses to start without it, so a live server that forgot it stops instead of quietly starting on an empty database.

## Tests

```
python manage.py test
```

They run on the database named by `TEST_DATABASE_URL`. On your own computer the same address as `DATABASE_URL` is fine, because Django makes and removes its own `test_` database. `manage.py test` ignores `DATABASE_URL`, so a test run can never touch the live database.

## Demo data

To try the site with 50 students, two teachers and a superadmin, or to test it hard, fill a **separate, empty** database with made-up accounts. The command refuses to run when the database is not on your computer, when real email is switched on, or when the database already holds any other account, so it cannot touch anything real.

In psql make the database (`CREATE DATABASE quizhub_demo;`), then in a PowerShell window (these settings last only for that window; on Linux or macOS use `export NAME=value`):

```
$env:DATABASE_URL = 'postgres://postgres:YOUR_PASSWORD@localhost:5432/quizhub_demo'
$env:EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

`seed_demo` prints the password all demo accounts share (a new random one each run; choose your own with `--password`), the exam links, and the authenticator key of the superadmin (`demo.admin`) and the teachers (`demo.teacher1`, `demo.teacher2`). Students are `zz0001` to `zz0050`. For the code step of a staff sign-in, `python manage.py seed_demo --code demo.teacher1` prints the current code. Running the command again keeps the data and gives everyone a new password and key.

## On a real server

A real server starts the site through gunicorn, not `manage.py`, so it is safe by default: debug is off, and the site refuses to start without `DJANGO_SECRET_KEY` (a long random string) and a host name (`DJANGO_ALLOWED_HOSTS`, or Render's own `RENDER_EXTERNAL_HOSTNAME`). The host's environment variables (`.env.example` explains each one): `DATABASE_URL` (for Neon use its direct address, the host WITHOUT `-pooler`), `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and behind a host's proxy `DJANGO_TRUSTED_PROXY_COUNT` and `DJANGO_ASSUME_HTTPS`.

Before the first start, with the same variables set **and `DJANGO_DEBUG=False`** (otherwise the static files get plain names), run `python manage.py collectstatic --noinput` and `python manage.py migrate`. Then start the site with `gunicorn quiz_project.wsgi:application` (Zoho runs it as `python3 -m gunicorn quiz_project.wsgi:application`).

`gunicorn.conf.py` is read automatically: it takes the port from `X_ZOHO_CATALYST_LISTEN_PORT` (Zoho) or `PORT` (Render and most hosts) and runs ONE process with 8 threads. One process is on purpose, because the login locks and rate limits are kept in its memory; with several processes or instances each would count on its own, and a shared cache would be needed. gunicorn only runs on Linux; on Windows use `runserver`. To check the settings, run `python manage.py check --deploy` with the same variables set (it reports nothing when `DJANGO_ASSUME_HTTPS` is on, because such a host does HTTPS and HSTS itself).

## Deploying to Zoho Catalyst (AppSail)

1. **Keep the secrets in a private file outside the project** (the project is public on GitHub), for example `C:\Users\you\Documents\quizhub_secrets.env`, one `NAME=value` per line. It must have `DATABASE_URL` (Neon's direct address). It may also have `DJANGO_SECRET_KEY` (made and saved into the file when it is missing, so every build keeps the same one), `DJANGO_ALLOWED_HOSTS` (`.catalystappsail.in` unless you give the exact host name), `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL`.
2. **Build the folder Zoho uploads.** `python deploy/build_zoho.py --secrets-file C:\Users\you\Documents\quizhub_secrets.env` makes it next to the project folder (`..\quizhub_zoho`, never inside it): the code, the collected static files, the Linux versions of the packages (one pip command, printed before it runs; nothing is installed on your computer) and an `app-config.json` with the start command, the settings that are not secrets and the secrets from your file. Only the six names above are copied (anything else in the file stays behind) and no value is ever printed. That folder now holds secrets: keep it private and delete it after deploying. Without `--secrets-file` the secrets go into the Zoho console instead. It needs Python 3.13 and your own `pip install -r requirements.txt` done first. Run it again after every code change; add `--skip-packages` for a quick rebuild when only the code changed.
3. **The first time only:** in that folder run `catalyst init` (AppSail, Catalyst-managed runtime, Python 3.13, source directory `.`). Then, in the project folder, run the build script again with `--config-only` (and the same `--secrets-file`): it puts the start command and the settings back into the `app-config.json` that `catalyst init` made.
4. **Deploy:** `catalyst deploy` in the Zoho folder.
5. **The database:** from your own computer (on a network that allows the database port), with `DATABASE_URL` set for that one window only, run `python manage.py migrate`, then `python manage.py ensure_superuser` with `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` and `DJANGO_SUPERUSER_PASSWORD` set the same way (or `createsuperuser`). They are not run when the site starts, because the site must be listening within 10 seconds.

## Deploying to Render

`render.yaml` (the service), `build.sh` (what each build runs) and `.python-version` (Python 3.13) are everything Render needs.

1. In Render choose **New > Blueprint** and pick this repository. It makes the web service (the free one, in Singapore, next to the Neon database) and asks for four values: `DATABASE_URL` (Neon's direct address) and the first superadmin's `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` and `DJANGO_SUPERUSER_PASSWORD` (at least 12 characters). The secret key is made by Render itself.
2. Every deploy runs `build.sh`: it installs the packages, collects the static files, applies the database migrations and makes the superadmin if there is none yet. Merging to `main` deploys again by itself.
3. When the first deploy is live, sign in as the superadmin (you set up the authenticator at the first sign-in), then remove `DJANGO_SUPERUSER_PASSWORD` from the service's environment.
4. Open **Locked logins** (superadmin) and read "How the site sees your address". Set `DJANGO_TRUSTED_PROXY_COUNT` to the number whose row shows your real address (Render's proxies sit in front of the site). Until then it is 0, which trusts no header.
5. A free service goes to sleep after 15 minutes without a visit and takes about a minute to wake, so open the site a couple of minutes before a class. It also cannot send mail on ports 25, 465 and 587, so Gmail will not work there: use a mail service's SMTP on port 2525 (set `EMAIL_HOST`, `EMAIL_PORT=2525`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL`) or a paid instance. Until mail is set up, the emails are only written to the service's log.

## Locked out of two-factor?

A superadmin who has lost both their phone and their recovery codes can be let back in from the server:

```
python manage.py reset_two_factor <username>
```
