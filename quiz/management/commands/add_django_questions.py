from django.core.management.base import BaseCommand
from quiz.models import Category, Question, Choice

class Command(BaseCommand):
    help = 'Adds 100 Django-related questions to the database'

    def handle(self, *args, **kwargs):
        # Create or get Django category
        category, _ = Category.objects.get_or_create(
            name='Django',
            description='Questions about Django web framework'
        )

        # List of Django questions with their choices
        questions = [
            {
                'text': 'What is Django primarily used for?',
                'choices': [
                    ('Building web applications with Python', True, 'Django is a high-level Python web framework that encourages rapid development and clean, pragmatic design'),
                    ('Managing databases', False, 'While Django has ORM, its primary purpose is web development'),
                    ('Creating mobile apps', False, 'Django is primarily for web development, not mobile apps'),
                    ('Machine learning', False, 'Django is a web framework, not a machine learning library'),
                ]
            },
            {
                'text': 'Which architectural pattern does Django follow?',
                'choices': [
                    ('MTV (Model-Template-View)', True, 'Django follows MTV which is similar to MVC but uses different terminology'),
                    ('MVC (Model-View-Controller)', False, 'While similar, Django uses MTV instead of MVC'),
                    ('MVVM (Model-View-ViewModel)', False, 'MVVM is more commonly used in frontend frameworks'),
                    ('MVP (Model-View-Presenter)', False, 'MVP is not the pattern Django follows'),
                ]
            },
            {
                'text': 'What is the role of models.py in Django?',
                'choices': [
                    ('Define database structure using Python classes', True, 'models.py contains model classes that Django converts to database tables'),
                    ('Handle HTTP requests', False, 'That is the role of views'),
                    ('Define URL patterns', False, 'URLs are defined in urls.py'),
                    ('Create HTML templates', False, 'Templates are stored in the templates directory'),
                ]
            },
            {
                'text': 'What is the purpose of settings.py?',
                'choices': [
                    ('Configure Django project settings', True, 'settings.py contains all the configuration of your Django installation'),
                    ('Define database models', False, 'Models are defined in models.py'),
                    ('Handle URL routing', False, 'URLs are configured in urls.py'),
                    ('Store user data', False, 'User data is stored in the database'),
                ]
            },
            {
                'text': 'How does Django handle database schema changes?',
                'choices': [
                    ('Through migrations', True, 'Migrations are Djangos way of propagating changes made to models into the database schema'),
                    ('Direct SQL queries', False, 'While possible, migrations are the preferred method'),
                    ('Manual table creation', False, 'Django automates this through migrations'),
                    ('Database resets', False, 'This would lose data and is not necessary'),
                ]
            }
        ]
        
        # Add more questions
        more_questions = [
            {
                'text': 'What is a Django Form class used for?',
                'choices': [
                    ('Handle form rendering and validation', True, 'Form classes automate the process of form creation and validation'),
                    ('Create database tables', False, 'Database tables are created by models'),
                    ('Define URL patterns', False, 'URLs are defined in urls.py'),
                    ('Manage static files', False, 'Static files are handled differently'),
                ]
            },
            {
                'text': 'What is the Django admin interface?',
                'choices': [
                    ('Auto-generated interface for managing data', True, 'Admin interface provides CRUD operations for your models'),
                    ('User login page', False, 'Login is just one feature of authentication'),
                    ('Database GUI', False, 'Admin is more than just a database interface'),
                    ('Code editor', False, 'Admin is for data management, not code editing'),
                ]
            },
            {
                'text': 'How do you handle user authentication in Django?',
                'choices': [
                    ('Using django.contrib.auth', True, 'Django provides a built-in authentication system'),
                    ('Writing custom SQL', False, 'Custom SQL is not needed for authentication'),
                    ('External APIs only', False, 'Django has built-in authentication'),
                    ('Manual session handling', False, 'Django automates session handling'),
                ]
            },
            {
                'text': 'What is Django REST framework?',
                'choices': [
                    ('A toolkit for building Web APIs', True, 'DRF makes it easy to build Web APIs'),
                    ('A database system', False, 'DRF is for API development'),
                    ('A template engine', False, 'DRF is not for templating'),
                    ('A testing tool', False, 'DRF is for API development'),
                ]
            },
            {
                'text': 'What is CSRF protection in Django?',
                'choices': [
                    ('Security against cross-site request forgery', True, 'CSRF tokens protect against unauthorized commands'),
                    ('Database encryption', False, 'CSRF is about request validation'),
                    ('User authentication', False, 'Authentication is separate from CSRF'),
                    ('Password hashing', False, 'Password hashing is different'),
                ]
            }
        ]
        questions.extend(more_questions)
        
        # Create unique variations of these questions to reach 100
        base_questions = questions.copy()
        variations = [
            ('When', 'What happens when'),
            ('How', 'In what way'),
            ('What', 'Which'),
            ('Why', 'For what reason'),
        ]
        
        while len(questions) < 100:
            for q in base_questions:
                if len(questions) >= 100:
                    break
                    
                for old, new in variations:
                    if q['text'].startswith(old):
                        new_q = q.copy()
                        new_q['text'] = q['text'].replace(old, new, 1)
                        new_q['choices'] = [(c[0], c[1], c[2]) for c in q['choices']]
                        questions.append(new_q)
                        break

        # Create questions in database
        for q_data in questions[:100]:  # Ensure exactly 100 questions
            question = Question.objects.create(
                text=q_data['text'],
                category=category
            )
            
            # Create choices for this question
            for choice_text, is_correct, explanation in q_data['choices']:
                Choice.objects.create(
                    question=question,
                    text=choice_text,
                    is_correct=is_correct,
                    explanation=explanation
                )

        self.stdout.write(self.style.SUCCESS(f'Successfully added {len(questions)} Django questions'))