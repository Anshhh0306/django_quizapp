# QuizHub

A Django site for running class tests. Teachers build a test from a CSV or Excel file, share one link, and follow it live. Students open the link, sign in with their college email, and take it.

## What it does

- **Accounts**: students register with an `@srmist.edu.in` address and confirm it by email. Teachers register the same way and wait for a superadmin to approve them.
- **Tests**: a teacher uploads questions, picks the ones to use, sets a seat limit and an optional class list, and shares the link. A test is either *scheduled* (the teacher starts it, with a fixed time) or *open* (anytime, no timer).
- **Live control**: the teacher sees who is in the lobby and who is working, can freeze a seat, give extra time, and look at results.
- **Anti-cheat**: the server keeps the clock and locks a test to one browser. Leaving the exam window counts as a strike, and the third submits the test.
- **Security**: two-factor sign-in is required for teachers and superadmins. Repeated wrong passwords lock the account for a while.

## Run it on your computer

```
git clone https://github.com/Anshhh0306/django_quizapp.git
cd django_quizapp
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux / macOS: cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open http://127.0.0.1:8000/. Without a mail password in `.env`, the emails (verification links, resets) are printed in the terminal instead of being sent.

## Settings

All settings come from environment variables or `.env`. See `.env.example`. On a real server, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False` and `DJANGO_ALLOWED_HOSTS` are all required or the site refuses to start. Never commit `.env`: it holds the mail password.

## Tests

```
python manage.py test
```

## Locked out of two-factor?

A superadmin who has lost both their phone and their recovery codes can be let back in from the server:

```
python manage.py reset_two_factor <username>
```
