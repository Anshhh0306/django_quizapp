# 🎯 QuizHub - Django Quiz Platform (`django_quizapp`)

A feature-packed, secure Django web application designed for interactive quizzes, anti-cheat test taking, user analytics, and email-verified institutional accounts.

![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)
![Django Version](https://img.shields.io/badge/django-5.2-green.svg)
![Tests](https://img.shields.io/badge/tests-17%20passed-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-purple.svg)

---

## ✨ Features

- 🔐 **Institutional Email Authentication**: Dedicated registration system restricting signups to verified `@srmist.edu.in` accounts with secure activation tokens.
- ⏱️ **Interactive Quiz Engine**: Timed questions, real-time score tracking, instant feedback explanations, and random choice shuffling.
- 🛡️ **Anti-Cheat Monitoring**: Fullscreen enforcement, focus-loss detection, tab-switching warnings, and automatic submission upon violation.
- 📊 **Leaderboard & Analytics**: Live leaderboard with tie handling, average score computations, category performance breakdowns, and user profile analytics.
- 🛠️ **Custom Admin Panel**: Dedicated Django administration suite with user activation/deactivation buttons, password resets, and choice inline inspection.
- 📧 **Configurable Email Support**: Gmail SMTP with automated fallback to Django console backend for seamless local development.
- 🧪 **100% Automated Test Suite**: Built-in unit and integration test coverage for models, views, custom middleware, and management commands.

---

## 📁 Project Structure

```
django_quizapp/
├── quiz_project/               # Project configuration & settings
│   ├── settings.py             # App settings with .env support & STATIC_ROOT
│   ├── urls.py                 # Root URL configuration
│   ├── wsgi.py                 # WSGI production server interface
│   └── asgi.py                 # ASGI configuration
├── quiz/                       # Main application
│   ├── models.py               # Category, Question, Choice, UserQuiz, UserStatistics
│   ├── views.py                # Quiz engine, auth, results, leaderboard views
│   ├── forms.py                # Registration and validation forms
│   ├── urls.py                 # Quiz route mappings
│   ├── admin.py                # ModelAdmin registrations
│   ├── user_admin.py           # Custom user administration actions
│   ├── middleware.py           # AdminAccessMiddleware security layer
│   ├── tokens.py               # Email verification token generator
│   ├── tests.py                # Unit and integration test suite
│   ├── fixtures/
│   │   └── questions_data.json # Initial question bank fixture
│   ├── management/commands/    # Custom management commands
│   │   ├── add_questions.py
│   │   ├── add_django_questions.py
│   │   ├── create_test_users.py
│   │   ├── clear_users.py
│   │   └── create_unique_questions.py
│   └── templates/              # HTML templates & email templates
├── static/                     # CSS stylesheets & assets
├── templates/                  # Base layout templates
├── manage.py                   # Django CLI management script
├── requirements.txt            # Dependencies
├── .env.example                # Environment variables template
└── README.md
```

---

## 🚀 Getting Started

### 1. Clone the Repository
```bash
git clone https://github.com/Anshhh0306/django_quizapp.git
cd django_quizapp
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.\.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the sample environment file:
```bash
cp .env.example .env
```
Edit `.env` to configure your custom `DJANGO_SECRET_KEY` and optional Gmail SMTP credentials (`EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`). If no password is provided, verification emails will output to the terminal console automatically.

### 5. Apply Database Migrations
```bash
python manage.py migrate
```

### 6. Load Sample Questions
Load the included question bank fixture:
```bash
python manage.py loaddata quiz/fixtures/questions_data.json
```
Or run the interactive question generator command:
```bash
python manage.py add_django_questions
```

### 7. Create Superuser (Optional)
```bash
python manage.py createsuperuser
```

### 8. Run Development Server
```bash
python manage.py runserver
```
Navigate to `http://127.0.0.1:8000/` in your browser.

---

## 🧪 Running Automated Tests

Run the full automated test suite:
```bash
python manage.py test
```

---

## 📦 Useful Management Commands

- `python manage.py add_questions` - Adds sample Django questions to the database.
- `python manage.py add_django_questions` - Adds a comprehensive bank of 100 Django questions.
- `python manage.py create_test_users` - Simulates test users with quiz scores for testing leaderboards.
- `python manage.py clear_users` - Cleans non-superuser accounts from the database.

---

## 📄 License
This project is licensed under the MIT License.
