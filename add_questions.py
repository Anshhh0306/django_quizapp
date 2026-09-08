import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quiz_project.settings')
django.setup()

from quiz.models import Category, Question, Choice

def add_questions():
    category = Category.objects.first()
    if not category:
        category = Category.objects.create(name="Django", description="Django Fundamentals")
        print(f"Created default category: {category.name}")
    
    questions = [
        {
            "text": "What command is used to create a new Django project?",
            "choices": [
                ("django-admin startproject myproject", True, "This is the correct command to create a new Django project"),
                ("python manage.py startproject", False, "This command by itself is incomplete"),
                ("django new project", False, "This is not a valid Django command"),
                ("django create project", False, "This is not a valid Django command")
            ]
        },
        {
            "text": "What is the default database in Django?",
            "choices": [
                ("SQLite", True, "SQLite is the default database in Django"),
                ("PostgreSQL", False, "PostgreSQL is supported but not the default"),
                ("MySQL", False, "MySQL is supported but not the default"),
                ("MongoDB", False, "MongoDB is NoSQL and not supported out of the box")
            ]
        }
    ]
    
    for q_data in questions:
        q, _ = Question.objects.get_or_create(text=q_data["text"], category=category)
        for choice_text, is_correct, explanation in q_data["choices"]:
            Choice.objects.get_or_create(
                question=q,
                text=choice_text,
                defaults={
                    "is_correct": is_correct,
                    "explanation": explanation
                }
            )
    print("Sample questions successfully added!")

if __name__ == "__main__":
    add_questions()
