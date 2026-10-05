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

Settings come from environment variables or a file called `.env`. `.env.example` lists them all; the three that only a real server needs are switched off. Copy the lines you need. On a real server, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False` and `DJANGO_ALLOWED_HOSTS` are all required or the site refuses to start. Never commit `.env`: it holds passwords.

## Database

PostgreSQL only. `DATABASE_URL` (for example `postgres://USER:PASSWORD@HOST:5432/DATABASE`) names the database, and the site refuses to start without it, so a live server that forgot it stops instead of quietly starting on an empty database.

## Tests

```
python manage.py test
```

They run on the database named by `TEST_DATABASE_URL`. On your own computer the same address as `DATABASE_URL` is fine, because Django makes and removes its own `test_` database. `manage.py test` ignores `DATABASE_URL`, so a test run can never touch the live database.

## Locked out of two-factor?

A superadmin who has lost both their phone and their recovery codes can be let back in from the server:

```
python manage.py reset_two_factor <username>
```
