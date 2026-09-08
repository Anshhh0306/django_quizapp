from django.core.management.base import BaseCommand
from quiz.models import Category, Question, Choice

class Command(BaseCommand):
    help = "Add sample Django questions"
    
    def handle(self, *args, **kwargs):
        category = Category.objects.first()
        if not category:
            self.stdout.write(self.style.ERROR("No category found"))
            return
            
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
                        'is_correct': is_correct,
                        'explanation': explanation
                    }
                )
                
        self.stdout.write(self.style.SUCCESS("Added sample questions"))
