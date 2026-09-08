from django.core.management.base import BaseCommand
from quiz.models import Question, Choice, Category

class Command(BaseCommand):
    help = 'Create 100 unique Django questions with different options'

    def handle(self, *args, **options):
        # Get or create Django category
        django_category, created = Category.objects.get_or_create(name='Django')
        
        # Clear existing questions for this category
        Question.objects.filter(category=django_category).delete()
        self.stdout.write('Cleared existing Django questions')

        # 100 unique Django questions with 4 options each
        questions_data = [
            {
                'text': 'What is Django primarily used for?',
                'choices': [
                    {'text': 'Web development', 'is_correct': True, 'explanation': 'Django is a high-level Python web framework.'},
                    {'text': 'Mobile app development', 'is_correct': False, 'explanation': 'Django is not primarily for mobile apps.'},
                    {'text': 'Desktop applications', 'is_correct': False, 'explanation': 'Django is web-focused, not desktop.'},
                    {'text': 'Game development', 'is_correct': False, 'explanation': 'Django is not used for game development.'}
                ]
            },
            {
                'text': 'Which architectural pattern does Django follow?',
                'choices': [
                    {'text': 'Model-View-Template (MVT)', 'is_correct': True, 'explanation': 'Django uses MVT architecture.'},
                    {'text': 'Model-View-Controller (MVC)', 'is_correct': False, 'explanation': 'Django uses MVT, not MVC.'},
                    {'text': 'Model-View-Presenter (MVP)', 'is_correct': False, 'explanation': 'Django does not use MVP pattern.'},
                    {'text': 'Component-Based Architecture', 'is_correct': False, 'explanation': 'Django follows MVT pattern.'}
                ]
            },
            {
                'text': 'What is the purpose of Django\'s ORM?',
                'choices': [
                    {'text': 'Database abstraction and object-relational mapping', 'is_correct': True, 'explanation': 'ORM maps database tables to Python objects.'},
                    {'text': 'User authentication', 'is_correct': False, 'explanation': 'ORM is for database operations, not auth.'},
                    {'text': 'Template rendering', 'is_correct': False, 'explanation': 'ORM handles database, not templates.'},
                    {'text': 'URL routing', 'is_correct': False, 'explanation': 'ORM is for database abstraction.'}
                ]
            },
            {
                'text': 'Which command creates a new Django project?',
                'choices': [
                    {'text': 'django-admin startproject', 'is_correct': True, 'explanation': 'This command creates a new Django project.'},
                    {'text': 'python manage.py createproject', 'is_correct': False, 'explanation': 'This is not a valid Django command.'},
                    {'text': 'django-admin newproject', 'is_correct': False, 'explanation': 'The correct command is startproject.'},
                    {'text': 'python django.py startproject', 'is_correct': False, 'explanation': 'Use django-admin, not python django.py.'}
                ]
            },
            {
                'text': 'What is the purpose of Django migrations?',
                'choices': [
                    {'text': 'Track and apply database schema changes', 'is_correct': True, 'explanation': 'Migrations handle database schema evolution.'},
                    {'text': 'Move files between directories', 'is_correct': False, 'explanation': 'Migrations are for database changes.'},
                    {'text': 'Import data from external sources', 'is_correct': False, 'explanation': 'Migrations handle schema, not data import.'},
                    {'text': 'Deploy code to production', 'is_correct': False, 'explanation': 'Migrations are for database schema management.'}
                ]
            },
            {
                'text': 'Which file contains Django project settings?',
                'choices': [
                    {'text': 'settings.py', 'is_correct': True, 'explanation': 'settings.py contains all project configuration.'},
                    {'text': 'config.py', 'is_correct': False, 'explanation': 'Django uses settings.py, not config.py.'},
                    {'text': 'django.conf', 'is_correct': False, 'explanation': 'This is not the settings file.'},
                    {'text': 'app.py', 'is_correct': False, 'explanation': 'Settings are in settings.py.'}
                ]
            },
            {
                'text': 'What does "Don\'t Repeat Yourself" (DRY) principle mean in Django?',
                'choices': [
                    {'text': 'Avoid code duplication and write reusable components', 'is_correct': True, 'explanation': 'DRY promotes code reusability and reduces duplication.'},
                    {'text': 'Never use the same variable name twice', 'is_correct': False, 'explanation': 'DRY is about code structure, not variable names.'},
                    {'text': 'Always create new functions instead of using existing ones', 'is_correct': False, 'explanation': 'DRY encourages reusing existing code.'},
                    {'text': 'Write code only once and never modify it', 'is_correct': False, 'explanation': 'DRY is about avoiding duplication, not immutability.'}
                ]
            },
            {
                'text': 'Which Django component handles URL routing?',
                'choices': [
                    {'text': 'URLconf (urls.py)', 'is_correct': True, 'explanation': 'URLconf maps URLs to views.'},
                    {'text': 'Views.py', 'is_correct': False, 'explanation': 'Views handle requests, URLconf handles routing.'},
                    {'text': 'Models.py', 'is_correct': False, 'explanation': 'Models represent data, not URL routing.'},
                    {'text': 'Templates', 'is_correct': False, 'explanation': 'Templates render HTML, not handle routing.'}
                ]
            },
            {
                'text': 'What is Django\'s default database?',
                'choices': [
                    {'text': 'SQLite', 'is_correct': True, 'explanation': 'SQLite is Django\'s default database for development.'},
                    {'text': 'PostgreSQL', 'is_correct': False, 'explanation': 'PostgreSQL is supported but not default.'},
                    {'text': 'MySQL', 'is_correct': False, 'explanation': 'MySQL is supported but not default.'},
                    {'text': 'Oracle', 'is_correct': False, 'explanation': 'Oracle is supported but not default.'}
                ]
            },
            {
                'text': 'Which decorator is used to require login for a view?',
                'choices': [
                    {'text': '@login_required', 'is_correct': True, 'explanation': 'This decorator ensures user authentication.'},
                    {'text': '@require_login', 'is_correct': False, 'explanation': 'The correct decorator is @login_required.'},
                    {'text': '@authenticated', 'is_correct': False, 'explanation': 'Django uses @login_required.'},
                    {'text': '@user_required', 'is_correct': False, 'explanation': 'The correct decorator is @login_required.'}
                ]
            },
            {
                'text': 'What is the purpose of Django middleware?',
                'choices': [
                    {'text': 'Process requests and responses globally', 'is_correct': True, 'explanation': 'Middleware runs before views and after responses.'},
                    {'text': 'Store session data', 'is_correct': False, 'explanation': 'Middleware processes requests/responses.'},
                    {'text': 'Render templates', 'is_correct': False, 'explanation': 'Templates are rendered by views, not middleware.'},
                    {'text': 'Define database models', 'is_correct': False, 'explanation': 'Models define data structure, not middleware.'}
                ]
            },
            {
                'text': 'Which command creates a new Django app?',
                'choices': [
                    {'text': 'python manage.py startapp', 'is_correct': True, 'explanation': 'This command creates a new Django application.'},
                    {'text': 'django-admin createapp', 'is_correct': False, 'explanation': 'Use python manage.py startapp.'},
                    {'text': 'python manage.py newapp', 'is_correct': False, 'explanation': 'The correct command is startapp.'},
                    {'text': 'django-admin startapp', 'is_correct': False, 'explanation': 'Use manage.py, not django-admin for apps.'}
                ]
            },
            {
                'text': 'What is a Django QuerySet?',
                'choices': [
                    {'text': 'A collection of database query results', 'is_correct': True, 'explanation': 'QuerySets represent database query results.'},
                    {'text': 'A type of Django form', 'is_correct': False, 'explanation': 'QuerySets are for database queries, not forms.'},
                    {'text': 'A template tag', 'is_correct': False, 'explanation': 'QuerySets are ORM objects, not template tags.'},
                    {'text': 'A URL pattern', 'is_correct': False, 'explanation': 'QuerySets handle database data.'}
                ]
            },
            {
                'text': 'Which method is used to save a model instance?',
                'choices': [
                    {'text': 'save()', 'is_correct': True, 'explanation': 'The save() method persists model instances.'},
                    {'text': 'commit()', 'is_correct': False, 'explanation': 'Django models use save(), not commit().'},
                    {'text': 'store()', 'is_correct': False, 'explanation': 'Django uses save() method.'},
                    {'text': 'persist()', 'is_correct': False, 'explanation': 'The correct method is save().'}
                ]
            },
            {
                'text': 'What is Django\'s template engine used for?',
                'choices': [
                    {'text': 'Generating dynamic HTML content', 'is_correct': True, 'explanation': 'Templates combine HTML with dynamic data.'},
                    {'text': 'Database operations', 'is_correct': False, 'explanation': 'Templates render HTML, not handle databases.'},
                    {'text': 'URL routing', 'is_correct': False, 'explanation': 'Templates are for HTML generation.'},
                    {'text': 'User authentication', 'is_correct': False, 'explanation': 'Templates render content, not handle auth.'}
                ]
            },
            {
                'text': 'Which file defines Django model fields?',
                'choices': [
                    {'text': 'models.py', 'is_correct': True, 'explanation': 'Models.py contains model definitions and fields.'},
                    {'text': 'fields.py', 'is_correct': False, 'explanation': 'Django uses models.py for model definitions.'},
                    {'text': 'database.py', 'is_correct': False, 'explanation': 'Models are defined in models.py.'},
                    {'text': 'schema.py', 'is_correct': False, 'explanation': 'Django models are in models.py.'}
                ]
            },
            {
                'text': 'What does CSRF protection prevent?',
                'choices': [
                    {'text': 'Cross-Site Request Forgery attacks', 'is_correct': True, 'explanation': 'CSRF tokens prevent unauthorized requests.'},
                    {'text': 'SQL injection attacks', 'is_correct': False, 'explanation': 'CSRF protects against request forgery, not SQL injection.'},
                    {'text': 'XSS attacks', 'is_correct': False, 'explanation': 'CSRF is for request forgery, not XSS.'},
                    {'text': 'DDoS attacks', 'is_correct': False, 'explanation': 'CSRF prevents request forgery attacks.'}
                ]
            },
            {
                'text': 'Which Django form field validates email addresses?',
                'choices': [
                    {'text': 'EmailField', 'is_correct': True, 'explanation': 'EmailField validates email format.'},
                    {'text': 'CharField', 'is_correct': False, 'explanation': 'CharField is generic, EmailField is specific.'},
                    {'text': 'TextField', 'is_correct': False, 'explanation': 'TextField is for large text, not email validation.'},
                    {'text': 'URLField', 'is_correct': False, 'explanation': 'URLField is for URLs, not emails.'}
                ]
            },
            {
                'text': 'What is the purpose of Django admin?',
                'choices': [
                    {'text': 'Provide an administrative interface for models', 'is_correct': True, 'explanation': 'Django admin offers CRUD operations for models.'},
                    {'text': 'Handle user authentication', 'is_correct': False, 'explanation': 'Admin is for model management, not just auth.'},
                    {'text': 'Generate API endpoints', 'is_correct': False, 'explanation': 'Admin provides web interface, not APIs.'},
                    {'text': 'Manage static files', 'is_correct': False, 'explanation': 'Admin is for model administration.'}
                ]
            },
            {
                'text': 'Which command runs Django development server?',
                'choices': [
                    {'text': 'python manage.py runserver', 'is_correct': True, 'explanation': 'This command starts the development server.'},
                    {'text': 'django-admin serve', 'is_correct': False, 'explanation': 'Use manage.py runserver.'},
                    {'text': 'python manage.py startserver', 'is_correct': False, 'explanation': 'The correct command is runserver.'},
                    {'text': 'django-admin runserver', 'is_correct': False, 'explanation': 'Use python manage.py runserver.'}
                ]
            },
            {
                'text': 'What is a Django ForeignKey used for?',
                'choices': [
                    {'text': 'Creating relationships between models', 'is_correct': True, 'explanation': 'ForeignKey creates many-to-one relationships.'},
                    {'text': 'Storing large text data', 'is_correct': False, 'explanation': 'ForeignKey is for relationships, not text storage.'},
                    {'text': 'Validating form input', 'is_correct': False, 'explanation': 'ForeignKey defines model relationships.'},
                    {'text': 'Encrypting sensitive data', 'is_correct': False, 'explanation': 'ForeignKey is for database relationships.'}
                ]
            },
            {
                'text': 'Which Django field type stores True/False values?',
                'choices': [
                    {'text': 'BooleanField', 'is_correct': True, 'explanation': 'BooleanField stores boolean values.'},
                    {'text': 'CharField', 'is_correct': False, 'explanation': 'CharField stores text, not boolean values.'},
                    {'text': 'IntegerField', 'is_correct': False, 'explanation': 'IntegerField stores numbers, not booleans.'},
                    {'text': 'TextField', 'is_correct': False, 'explanation': 'TextField stores text, not boolean values.'}
                ]
            },
            {
                'text': 'What does the Django {% csrf_token %} template tag do?',
                'choices': [
                    {'text': 'Adds CSRF protection to forms', 'is_correct': True, 'explanation': 'This tag includes CSRF token in forms.'},
                    {'text': 'Creates a user session', 'is_correct': False, 'explanation': 'CSRF token is for form security.'},
                    {'text': 'Renders static files', 'is_correct': False, 'explanation': 'CSRF token is for form protection.'},
                    {'text': 'Includes other templates', 'is_correct': False, 'explanation': 'CSRF token adds security to forms.'}
                ]
            },
            {
                'text': 'Which Django view type is function-based?',
                'choices': [
                    {'text': 'def my_view(request)', 'is_correct': True, 'explanation': 'Function-based views are Python functions.'},
                    {'text': 'class MyView(View)', 'is_correct': False, 'explanation': 'This is a class-based view.'},
                    {'text': 'MyView.as_view()', 'is_correct': False, 'explanation': 'This creates a view from a class.'},
                    {'text': '@method_decorator', 'is_correct': False, 'explanation': 'This is a decorator, not a view type.'}
                ]
            },
            {
                'text': 'What is Django\'s default session backend?',
                'choices': [
                    {'text': 'Database', 'is_correct': True, 'explanation': 'Django stores sessions in database by default.'},
                    {'text': 'File system', 'is_correct': False, 'explanation': 'File system is optional, database is default.'},
                    {'text': 'Cache', 'is_correct': False, 'explanation': 'Cache is optional, database is default.'},
                    {'text': 'Cookies', 'is_correct': False, 'explanation': 'Cookies store session ID, data is in database.'}
                ]
            },
            {
                'text': 'Which command applies Django migrations?',
                'choices': [
                    {'text': 'python manage.py migrate', 'is_correct': True, 'explanation': 'This command applies migrations to database.'},
                    {'text': 'python manage.py makemigrations', 'is_correct': False, 'explanation': 'makemigrations creates migrations, migrate applies them.'},
                    {'text': 'python manage.py syncdb', 'is_correct': False, 'explanation': 'syncdb is deprecated, use migrate.'},
                    {'text': 'python manage.py applymigrations', 'is_correct': False, 'explanation': 'The correct command is migrate.'}
                ]
            },
            {
                'text': 'What is the purpose of Django forms?',
                'choices': [
                    {'text': 'Handle HTML forms and validate user input', 'is_correct': True, 'explanation': 'Django forms validate and process form data.'},
                    {'text': 'Store data in database', 'is_correct': False, 'explanation': 'Forms validate input, models store data.'},
                    {'text': 'Generate URLs', 'is_correct': False, 'explanation': 'Forms handle input validation, not URLs.'},
                    {'text': 'Render templates', 'is_correct': False, 'explanation': 'Forms process input, templates render HTML.'}
                ]
            },
            {
                'text': 'Which Django field stores date and time?',
                'choices': [
                    {'text': 'DateTimeField', 'is_correct': True, 'explanation': 'DateTimeField stores both date and time.'},
                    {'text': 'DateField', 'is_correct': False, 'explanation': 'DateField stores only date, not time.'},
                    {'text': 'TimeField', 'is_correct': False, 'explanation': 'TimeField stores only time, not date.'},
                    {'text': 'CharField', 'is_correct': False, 'explanation': 'CharField stores text, not datetime.'}
                ]
            },
            {
                'text': 'What does Django\'s {% load %} template tag do?',
                'choices': [
                    {'text': 'Loads custom template tags and filters', 'is_correct': True, 'explanation': 'Load tag imports template libraries.'},
                    {'text': 'Loads static files', 'is_correct': False, 'explanation': 'Load tag is for template libraries.'},
                    {'text': 'Loads database data', 'is_correct': False, 'explanation': 'Load tag imports template functionality.'},
                    {'text': 'Loads other templates', 'is_correct': False, 'explanation': 'Load tag imports template libraries.'}
                ]
            },
            {
                'text': 'Which Django model method returns a string representation?',
                'choices': [
                    {'text': '__str__()', 'is_correct': True, 'explanation': '__str__ method defines string representation.'},
                    {'text': '__repr__()', 'is_correct': False, 'explanation': '__repr__ is for debugging, __str__ for display.'},
                    {'text': '__unicode__()', 'is_correct': False, 'explanation': '__unicode__ is for Python 2, use __str__.'},
                    {'text': 'toString()', 'is_correct': False, 'explanation': 'Python uses __str__, not toString().'}
                ]
            },
            {
                'text': 'What is Django\'s static files system used for?',
                'choices': [
                    {'text': 'Serving CSS, JavaScript, and images', 'is_correct': True, 'explanation': 'Static files serve unchanging assets.'},
                    {'text': 'Storing user uploads', 'is_correct': False, 'explanation': 'User uploads are media files, not static.'},
                    {'text': 'Caching database queries', 'is_correct': False, 'explanation': 'Static files are for assets, not caching.'},
                    {'text': 'Handling form submissions', 'is_correct': False, 'explanation': 'Static files serve assets, not handle forms.'}
                ]
            },
            {
                'text': 'Which Django setting defines installed applications?',
                'choices': [
                    {'text': 'INSTALLED_APPS', 'is_correct': True, 'explanation': 'INSTALLED_APPS lists all Django applications.'},
                    {'text': 'APPLICATIONS', 'is_correct': False, 'explanation': 'Django uses INSTALLED_APPS setting.'},
                    {'text': 'APPS_LIST', 'is_correct': False, 'explanation': 'The correct setting is INSTALLED_APPS.'},
                    {'text': 'DJANGO_APPS', 'is_correct': False, 'explanation': 'Django uses INSTALLED_APPS.'}
                ]
            },
            {
                'text': 'What is a Django slug field used for?',
                'choices': [
                    {'text': 'URL-friendly string identifiers', 'is_correct': True, 'explanation': 'Slugs create clean URLs from text.'},
                    {'text': 'Storing large files', 'is_correct': False, 'explanation': 'Slugs are for URL-friendly text.'},
                    {'text': 'User authentication', 'is_correct': False, 'explanation': 'Slugs are for URL formatting.'},
                    {'text': 'Database indexing', 'is_correct': False, 'explanation': 'Slugs create URL-friendly strings.'}
                ]
            },
            {
                'text': 'Which Django decorator caches view results?',
                'choices': [
                    {'text': '@cache_page', 'is_correct': True, 'explanation': 'cache_page decorator caches entire view output.'},
                    {'text': '@cached_view', 'is_correct': False, 'explanation': 'Django uses @cache_page decorator.'},
                    {'text': '@view_cache', 'is_correct': False, 'explanation': 'The correct decorator is @cache_page.'},
                    {'text': '@cacheable', 'is_correct': False, 'explanation': 'Django uses @cache_page for view caching.'}
                ]
            },
            {
                'text': 'What does Django\'s {% include %} template tag do?',
                'choices': [
                    {'text': 'Includes another template', 'is_correct': True, 'explanation': 'Include tag renders another template inline.'},
                    {'text': 'Includes static files', 'is_correct': False, 'explanation': 'Include tag is for templates, not static files.'},
                    {'text': 'Includes Python code', 'is_correct': False, 'explanation': 'Templates cannot include Python code directly.'},
                    {'text': 'Includes database queries', 'is_correct': False, 'explanation': 'Include tag renders templates.'}
                ]
            },
            {
                'text': 'Which Django field stores uploaded files?',
                'choices': [
                    {'text': 'FileField', 'is_correct': True, 'explanation': 'FileField handles file uploads.'},
                    {'text': 'BinaryField', 'is_correct': False, 'explanation': 'BinaryField stores binary data, not files.'},
                    {'text': 'TextField', 'is_correct': False, 'explanation': 'TextField stores text, not files.'},
                    {'text': 'CharField', 'is_correct': False, 'explanation': 'CharField stores text, not files.'}
                ]
            },
            {
                'text': 'What is Django\'s reverse() function used for?',
                'choices': [
                    {'text': 'Generate URLs from view names', 'is_correct': True, 'explanation': 'reverse() creates URLs from URL pattern names.'},
                    {'text': 'Reverse database migrations', 'is_correct': False, 'explanation': 'reverse() is for URL generation.'},
                    {'text': 'Reverse string data', 'is_correct': False, 'explanation': 'reverse() generates URLs from names.'},
                    {'text': 'Reverse form validation', 'is_correct': False, 'explanation': 'reverse() is for URL creation.'}
                ]
            },
            {
                'text': 'Which Django command creates database migrations?',
                'choices': [
                    {'text': 'python manage.py makemigrations', 'is_correct': True, 'explanation': 'makemigrations creates migration files.'},
                    {'text': 'python manage.py migrate', 'is_correct': False, 'explanation': 'migrate applies migrations, makemigrations creates them.'},
                    {'text': 'python manage.py createmigrations', 'is_correct': False, 'explanation': 'The correct command is makemigrations.'},
                    {'text': 'python manage.py genmigrations', 'is_correct': False, 'explanation': 'Django uses makemigrations command.'}
                ]
            },
            {
                'text': 'What is a Django ManyToManyField used for?',
                'choices': [
                    {'text': 'Creating many-to-many relationships between models', 'is_correct': True, 'explanation': 'ManyToManyField links multiple instances bidirectionally.'},
                    {'text': 'Storing multiple values in one field', 'is_correct': False, 'explanation': 'ManyToManyField creates relationships, not stores values.'},
                    {'text': 'Creating one-to-one relationships', 'is_correct': False, 'explanation': 'OneToOneField is for one-to-one relationships.'},
                    {'text': 'Storing JSON data', 'is_correct': False, 'explanation': 'ManyToManyField is for model relationships.'}
                ]
            },
            {
                'text': 'Which Django view method handles GET requests?',
                'choices': [
                    {'text': 'get()', 'is_correct': True, 'explanation': 'Class-based views use get() method for GET requests.'},
                    {'text': 'handle_get()', 'is_correct': False, 'explanation': 'Django uses get() method in class-based views.'},
                    {'text': 'process_get()', 'is_correct': False, 'explanation': 'The correct method is get().'},
                    {'text': 'on_get()', 'is_correct': False, 'explanation': 'Django class-based views use get() method.'}
                ]
            },
            {
                'text': 'What does Django\'s {% url %} template tag do?',
                'choices': [
                    {'text': 'Generates URLs from view names', 'is_correct': True, 'explanation': 'url tag creates URLs from URL pattern names.'},
                    {'text': 'Validates URL format', 'is_correct': False, 'explanation': 'url tag generates URLs, not validates them.'},
                    {'text': 'Redirects to another page', 'is_correct': False, 'explanation': 'url tag generates URLs for links.'},
                    {'text': 'Loads external URLs', 'is_correct': False, 'explanation': 'url tag creates internal URLs from names.'}
                ]
            },
            {
                'text': 'Which Django field automatically adds creation timestamp?',
                'choices': [
                    {'text': 'DateTimeField with auto_now_add=True', 'is_correct': True, 'explanation': 'auto_now_add sets timestamp on creation.'},
                    {'text': 'TimeStampField', 'is_correct': False, 'explanation': 'Django uses DateTimeField with auto_now_add.'},
                    {'text': 'CreatedField', 'is_correct': False, 'explanation': 'Use DateTimeField with auto_now_add=True.'},
                    {'text': 'AutoDateField', 'is_correct': False, 'explanation': 'Django uses DateTimeField with auto_now_add.'}
                ]
            },
            {
                'text': 'What is Django\'s signals system used for?',
                'choices': [
                    {'text': 'Execute code automatically when certain actions occur', 'is_correct': True, 'explanation': 'Signals trigger functions on model events.'},
                    {'text': 'Send emails to users', 'is_correct': False, 'explanation': 'Signals are for automatic code execution.'},
                    {'text': 'Handle HTTP requests', 'is_correct': False, 'explanation': 'Views handle requests, signals handle events.'},
                    {'text': 'Validate form data', 'is_correct': False, 'explanation': 'Signals execute code on database events.'}
                ]
            },
            {
                'text': 'Which Django setting defines the database configuration?',
                'choices': [
                    {'text': 'DATABASES', 'is_correct': True, 'explanation': 'DATABASES setting contains database configuration.'},
                    {'text': 'DATABASE_URL', 'is_correct': False, 'explanation': 'Django uses DATABASES setting.'},
                    {'text': 'DB_CONFIG', 'is_correct': False, 'explanation': 'The correct setting is DATABASES.'},
                    {'text': 'DATABASE_SETTINGS', 'is_correct': False, 'explanation': 'Django uses DATABASES for database config.'}
                ]
            },
            {
                'text': 'What is a Django ModelForm used for?',
                'choices': [
                    {'text': 'Automatically create forms from model fields', 'is_correct': True, 'explanation': 'ModelForm generates forms based on model structure.'},
                    {'text': 'Create database models', 'is_correct': False, 'explanation': 'ModelForm creates forms, not models.'},
                    {'text': 'Validate database data', 'is_correct': False, 'explanation': 'ModelForm validates form input, not database.'},
                    {'text': 'Generate model methods', 'is_correct': False, 'explanation': 'ModelForm creates forms from models.'}
                ]
            },
            {
                'text': 'Which Django field type stores decimal numbers accurately?',
                'choices': [
                    {'text': 'DecimalField', 'is_correct': True, 'explanation': 'DecimalField stores precise decimal values.'},
                    {'text': 'FloatField', 'is_correct': False, 'explanation': 'FloatField has precision issues, use DecimalField.'},
                    {'text': 'IntegerField', 'is_correct': False, 'explanation': 'IntegerField stores whole numbers, not decimals.'},
                    {'text': 'NumberField', 'is_correct': False, 'explanation': 'Django uses DecimalField for precise decimals.'}
                ]
            },
            {
                'text': 'What does Django\'s {% block %} template tag do?',
                'choices': [
                    {'text': 'Defines template sections that can be overridden', 'is_correct': True, 'explanation': 'Blocks allow template inheritance and customization.'},
                    {'text': 'Creates code blocks in templates', 'is_correct': False, 'explanation': 'Blocks are for template inheritance.'},
                    {'text': 'Blocks template rendering', 'is_correct': False, 'explanation': 'Blocks define overrideable sections.'},
                    {'text': 'Groups related template tags', 'is_correct': False, 'explanation': 'Blocks enable template inheritance.'}
                ]
            },
            {
                'text': 'Which Django command creates a superuser account?',
                'choices': [
                    {'text': 'python manage.py createsuperuser', 'is_correct': True, 'explanation': 'createsuperuser creates admin account.'},
                    {'text': 'python manage.py createadmin', 'is_correct': False, 'explanation': 'The correct command is createsuperuser.'},
                    {'text': 'python manage.py makeadmin', 'is_correct': False, 'explanation': 'Django uses createsuperuser command.'},
                    {'text': 'python manage.py addsuperuser', 'is_correct': False, 'explanation': 'The correct command is createsuperuser.'}
                ]
            },
            {
                'text': 'What is Django\'s context processor used for?',
                'choices': [
                    {'text': 'Add variables to all template contexts automatically', 'is_correct': True, 'explanation': 'Context processors provide global template variables.'},
                    {'text': 'Process form submissions', 'is_correct': False, 'explanation': 'Context processors add template variables.'},
                    {'text': 'Handle database queries', 'is_correct': False, 'explanation': 'Context processors provide template context.'},
                    {'text': 'Validate user permissions', 'is_correct': False, 'explanation': 'Context processors add global template data.'}
                ]
            },
            {
                'text': 'Which Django field validates URL format?',
                'choices': [
                    {'text': 'URLField', 'is_correct': True, 'explanation': 'URLField validates URL format automatically.'},
                    {'text': 'CharField', 'is_correct': False, 'explanation': 'CharField is generic, URLField validates URLs.'},
                    {'text': 'TextField', 'is_correct': False, 'explanation': 'TextField is for large text, not URL validation.'},
                    {'text': 'LinkField', 'is_correct': False, 'explanation': 'Django uses URLField for URL validation.'}
                ]
            },
            {
                'text': 'What is Django\'s {% extends %} template tag used for?',
                'choices': [
                    {'text': 'Inherit from a parent template', 'is_correct': True, 'explanation': 'extends enables template inheritance.'},
                    {'text': 'Extend template functionality', 'is_correct': False, 'explanation': 'extends is for template inheritance.'},
                    {'text': 'Add extra template tags', 'is_correct': False, 'explanation': 'extends inherits from parent templates.'},
                    {'text': 'Extend database models', 'is_correct': False, 'explanation': 'extends is for template inheritance.'}
                ]
            },
            {
                'text': 'Which Django method retrieves a single object?',
                'choices': [
                    {'text': 'get()', 'is_correct': True, 'explanation': 'get() method retrieves one object or raises exception.'},
                    {'text': 'find()', 'is_correct': False, 'explanation': 'Django uses get() method, not find().'},
                    {'text': 'fetch()', 'is_correct': False, 'explanation': 'Django ORM uses get() method.'},
                    {'text': 'retrieve()', 'is_correct': False, 'explanation': 'The correct method is get().'}
                ]
            },
            {
                'text': 'What does Django\'s collectstatic command do?',
                'choices': [
                    {'text': 'Copies static files to STATIC_ROOT directory', 'is_correct': True, 'explanation': 'collectstatic gathers static files for deployment.'},
                    {'text': 'Compresses static files', 'is_correct': False, 'explanation': 'collectstatic copies files, compression is separate.'},
                    {'text': 'Validates static file syntax', 'is_correct': False, 'explanation': 'collectstatic collects files for serving.'},
                    {'text': 'Creates static file URLs', 'is_correct': False, 'explanation': 'collectstatic copies files to deployment location.'}
                ]
            },
            {
                'text': 'Which Django field creates auto-incrementing primary keys?',
                'choices': [
                    {'text': 'AutoField', 'is_correct': True, 'explanation': 'AutoField creates auto-incrementing integer primary keys.'},
                    {'text': 'PrimaryKeyField', 'is_correct': False, 'explanation': 'Django uses AutoField for auto-increment keys.'},
                    {'text': 'IDField', 'is_correct': False, 'explanation': 'Django uses AutoField, not IDField.'},
                    {'text': 'SerialField', 'is_correct': False, 'explanation': 'Django uses AutoField for auto-incrementing IDs.'}
                ]
            },
            {
                'text': 'What is Django\'s {% for %} template tag used for?',
                'choices': [
                    {'text': 'Loop through sequences in templates', 'is_correct': True, 'explanation': 'for tag iterates over lists and querysets.'},
                    {'text': 'Create form elements', 'is_correct': False, 'explanation': 'for tag is for iteration, not forms.'},
                    {'text': 'Format text output', 'is_correct': False, 'explanation': 'for tag loops through data sequences.'},
                    {'text': 'Generate random numbers', 'is_correct': False, 'explanation': 'for tag iterates over collections.'}
                ]
            },
            {
                'text': 'Which Django setting controls allowed hosts?',
                'choices': [
                    {'text': 'ALLOWED_HOSTS', 'is_correct': True, 'explanation': 'ALLOWED_HOSTS defines valid host headers.'},
                    {'text': 'VALID_HOSTS', 'is_correct': False, 'explanation': 'Django uses ALLOWED_HOSTS setting.'},
                    {'text': 'PERMITTED_HOSTS', 'is_correct': False, 'explanation': 'The correct setting is ALLOWED_HOSTS.'},
                    {'text': 'HOST_WHITELIST', 'is_correct': False, 'explanation': 'Django uses ALLOWED_HOSTS for host validation.'}
                ]
            },
            {
                'text': 'What is Django\'s get_object_or_404() function used for?',
                'choices': [
                    {'text': 'Retrieve object or return 404 error if not found', 'is_correct': True, 'explanation': 'get_object_or_404 handles missing objects gracefully.'},
                    {'text': 'Create objects with default values', 'is_correct': False, 'explanation': 'get_object_or_404 retrieves existing objects.'},
                    {'text': 'Validate object permissions', 'is_correct': False, 'explanation': 'get_object_or_404 handles object retrieval.'},
                    {'text': 'Cache object queries', 'is_correct': False, 'explanation': 'get_object_or_404 retrieves objects with 404 fallback.'}
                ]
            },
            {
                'text': 'Which Django class-based view handles object creation?',
                'choices': [
                    {'text': 'CreateView', 'is_correct': True, 'explanation': 'CreateView provides form handling for new objects.'},
                    {'text': 'FormView', 'is_correct': False, 'explanation': 'FormView handles forms, CreateView handles object creation.'},
                    {'text': 'DetailView', 'is_correct': False, 'explanation': 'DetailView displays single objects, not creates them.'},
                    {'text': 'ListView', 'is_correct': False, 'explanation': 'ListView displays multiple objects.'}
                ]
            },
            {
                'text': 'What does Django\'s {% if %} template tag do?',
                'choices': [
                    {'text': 'Provides conditional logic in templates', 'is_correct': True, 'explanation': 'if tag enables conditional rendering.'},
                    {'text': 'Imports external files', 'is_correct': False, 'explanation': 'if tag provides conditional logic.'},
                    {'text': 'Validates form fields', 'is_correct': False, 'explanation': 'if tag is for conditional template logic.'},
                    {'text': 'Formats date values', 'is_correct': False, 'explanation': 'if tag provides conditional rendering.'}
                ]
            },
            {
                'text': 'Which Django field stores images specifically?',
                'choices': [
                    {'text': 'ImageField', 'is_correct': True, 'explanation': 'ImageField validates and stores image files.'},
                    {'text': 'FileField', 'is_correct': False, 'explanation': 'FileField is generic, ImageField is for images.'},
                    {'text': 'PhotoField', 'is_correct': False, 'explanation': 'Django uses ImageField for image storage.'},
                    {'text': 'PictureField', 'is_correct': False, 'explanation': 'Django uses ImageField for images.'}
                ]
            },
            {
                'text': 'What is Django\'s select_related() method used for?',
                'choices': [
                    {'text': 'Optimize database queries by following foreign keys', 'is_correct': True, 'explanation': 'select_related reduces database queries via JOINs.'},
                    {'text': 'Select specific model fields', 'is_correct': False, 'explanation': 'select_related optimizes foreign key queries.'},
                    {'text': 'Sort query results', 'is_correct': False, 'explanation': 'select_related is for query optimization.'},
                    {'text': 'Filter related objects', 'is_correct': False, 'explanation': 'select_related optimizes database access.'}
                ]
            },
            {
                'text': 'Which Django command shows current migration status?',
                'choices': [
                    {'text': 'python manage.py showmigrations', 'is_correct': True, 'explanation': 'showmigrations displays migration status.'},
                    {'text': 'python manage.py migrationstatus', 'is_correct': False, 'explanation': 'The correct command is showmigrations.'},
                    {'text': 'python manage.py listmigrations', 'is_correct': False, 'explanation': 'Django uses showmigrations command.'},
                    {'text': 'python manage.py checkmigrations', 'is_correct': False, 'explanation': 'The correct command is showmigrations.'}
                ]
            },
            {
                'text': 'What is Django\'s {% with %} template tag used for?',
                'choices': [
                    {'text': 'Create local variables in templates', 'is_correct': True, 'explanation': 'with tag creates scoped template variables.'},
                    {'text': 'Include external templates', 'is_correct': False, 'explanation': 'with tag creates local variables.'},
                    {'text': 'Connect to databases', 'is_correct': False, 'explanation': 'with tag is for template variable scoping.'},
                    {'text': 'Handle form submissions', 'is_correct': False, 'explanation': 'with tag creates local template context.'}
                ]
            },
            {
                'text': 'Which Django field validates positive numbers only?',
                'choices': [
                    {'text': 'PositiveIntegerField', 'is_correct': True, 'explanation': 'PositiveIntegerField only allows positive integers.'},
                    {'text': 'IntegerField with validators', 'is_correct': False, 'explanation': 'PositiveIntegerField is the specific field type.'},
                    {'text': 'NumberField', 'is_correct': False, 'explanation': 'Django uses PositiveIntegerField.'},
                    {'text': 'UnsignedIntegerField', 'is_correct': False, 'explanation': 'Django uses PositiveIntegerField.'}
                ]
            },
            {
                'text': 'What does Django\'s DEBUG setting control?',
                'choices': [
                    {'text': 'Enable detailed error pages and development features', 'is_correct': True, 'explanation': 'DEBUG shows detailed errors and enables dev tools.'},
                    {'text': 'Database query logging', 'is_correct': False, 'explanation': 'DEBUG controls error display and dev features.'},
                    {'text': 'Template caching behavior', 'is_correct': False, 'explanation': 'DEBUG affects error display and development mode.'},
                    {'text': 'Static file compression', 'is_correct': False, 'explanation': 'DEBUG controls development vs production behavior.'}
                ]
            },
            {
                'text': 'Which Django view method handles POST requests in class-based views?',
                'choices': [
                    {'text': 'post()', 'is_correct': True, 'explanation': 'Class-based views use post() method for POST requests.'},
                    {'text': 'handle_post()', 'is_correct': False, 'explanation': 'Django uses post() method in class-based views.'},
                    {'text': 'process_post()', 'is_correct': False, 'explanation': 'The correct method is post().'},
                    {'text': 'on_post()', 'is_correct': False, 'explanation': 'Django class-based views use post() method.'}
                ]
            },
            {
                'text': 'What is Django\'s prefetch_related() method used for?',
                'choices': [
                    {'text': 'Optimize queries for many-to-many and reverse foreign key relationships', 'is_correct': True, 'explanation': 'prefetch_related reduces queries for M2M relationships.'},
                    {'text': 'Preload template data', 'is_correct': False, 'explanation': 'prefetch_related optimizes database queries.'},
                    {'text': 'Cache query results', 'is_correct': False, 'explanation': 'prefetch_related optimizes relationship queries.'},
                    {'text': 'Validate related objects', 'is_correct': False, 'explanation': 'prefetch_related reduces database query count.'}
                ]
            },
            {
                'text': 'Which Django setting defines the secret key?',
                'choices': [
                    {'text': 'SECRET_KEY', 'is_correct': True, 'explanation': 'SECRET_KEY is used for cryptographic signing.'},
                    {'text': 'SECURITY_KEY', 'is_correct': False, 'explanation': 'Django uses SECRET_KEY setting.'},
                    {'text': 'CRYPTO_KEY', 'is_correct': False, 'explanation': 'The correct setting is SECRET_KEY.'},
                    {'text': 'PRIVATE_KEY', 'is_correct': False, 'explanation': 'Django uses SECRET_KEY for signing.'}
                ]
            },
            {
                'text': 'What is Django\'s {% comment %} template tag used for?',
                'choices': [
                    {'text': 'Add comments that are not rendered in output', 'is_correct': True, 'explanation': 'comment tag creates non-rendered template comments.'},
                    {'text': 'Display user comments', 'is_correct': False, 'explanation': 'comment tag is for template documentation.'},
                    {'text': 'Validate template syntax', 'is_correct': False, 'explanation': 'comment tag adds non-rendered notes.'},
                    {'text': 'Create form comments', 'is_correct': False, 'explanation': 'comment tag is for template comments.'}
                ]
            },
            {
                'text': 'Which Django class-based view displays a list of objects?',
                'choices': [
                    {'text': 'ListView', 'is_correct': True, 'explanation': 'ListView displays paginated object lists.'},
                    {'text': 'DetailView', 'is_correct': False, 'explanation': 'DetailView shows single objects, ListView shows lists.'},
                    {'text': 'TemplateView', 'is_correct': False, 'explanation': 'TemplateView renders templates, ListView shows object lists.'},
                    {'text': 'FormView', 'is_correct': False, 'explanation': 'FormView handles forms, ListView displays object lists.'}
                ]
            },
            {
                'text': 'What does Django\'s atomic() decorator do?',
                'choices': [
                    {'text': 'Ensures database operations are executed in a transaction', 'is_correct': True, 'explanation': 'atomic() wraps code in database transactions.'},
                    {'text': 'Makes variables thread-safe', 'is_correct': False, 'explanation': 'atomic() is for database transactions.'},
                    {'text': 'Optimizes memory usage', 'is_correct': False, 'explanation': 'atomic() handles database transaction integrity.'},
                    {'text': 'Prevents code duplication', 'is_correct': False, 'explanation': 'atomic() ensures transactional database operations.'}
                ]
            },
            {
                'text': 'Which Django field automatically updates on every save?',
                'choices': [
                    {'text': 'DateTimeField with auto_now=True', 'is_correct': True, 'explanation': 'auto_now updates timestamp on every save.'},
                    {'text': 'UpdatedField', 'is_correct': False, 'explanation': 'Use DateTimeField with auto_now=True.'},
                    {'text': 'ModifiedField', 'is_correct': False, 'explanation': 'Django uses DateTimeField with auto_now.'},
                    {'text': 'TimestampField', 'is_correct': False, 'explanation': 'Use DateTimeField with auto_now=True.'}
                ]
            },
            {
                'text': 'What is Django\'s {% firstof %} template tag used for?',
                'choices': [
                    {'text': 'Display the first non-empty variable from a list', 'is_correct': True, 'explanation': 'firstof shows the first truthy value.'},
                    {'text': 'Display the first item in a list', 'is_correct': False, 'explanation': 'firstof finds first non-empty variable.'},
                    {'text': 'Check if variable is first', 'is_correct': False, 'explanation': 'firstof displays first truthy value.'},
                    {'text': 'Sort variables by priority', 'is_correct': False, 'explanation': 'firstof returns first non-empty variable.'}
                ]
            },
            {
                'text': 'Which Django command validates the entire project?',
                'choices': [
                    {'text': 'python manage.py check', 'is_correct': True, 'explanation': 'check command validates project configuration.'},
                    {'text': 'python manage.py validate', 'is_correct': False, 'explanation': 'Django uses check command for validation.'},
                    {'text': 'python manage.py test_project', 'is_correct': False, 'explanation': 'The correct command is check.'},
                    {'text': 'python manage.py verify', 'is_correct': False, 'explanation': 'Django uses check for project validation.'}
                ]
            },
            {
                'text': 'What is Django\'s {% spaceless %} template tag used for?',
                'choices': [
                    {'text': 'Remove whitespace between HTML tags', 'is_correct': True, 'explanation': 'spaceless removes whitespace between tags.'},
                    {'text': 'Add spaces to text', 'is_correct': False, 'explanation': 'spaceless removes whitespace, not adds it.'},
                    {'text': 'Format code spacing', 'is_correct': False, 'explanation': 'spaceless removes HTML tag whitespace.'},
                    {'text': 'Validate template spacing', 'is_correct': False, 'explanation': 'spaceless removes whitespace between HTML tags.'}
                ]
            },
            {
                'text': 'Which Django field stores JSON data natively?',
                'choices': [
                    {'text': 'JSONField', 'is_correct': True, 'explanation': 'JSONField stores and queries JSON data efficiently.'},
                    {'text': 'TextField', 'is_correct': False, 'explanation': 'TextField stores text, JSONField handles JSON specifically.'},
                    {'text': 'DataField', 'is_correct': False, 'explanation': 'Django uses JSONField for JSON data.'},
                    {'text': 'ObjectField', 'is_correct': False, 'explanation': 'Django uses JSONField for JSON storage.'}
                ]
            },
            {
                'text': 'What does Django\'s {% now %} template tag do?',
                'choices': [
                    {'text': 'Display current date and time with formatting', 'is_correct': True, 'explanation': 'now tag shows current datetime with format options.'},
                    {'text': 'Get current user session', 'is_correct': False, 'explanation': 'now tag displays current date/time.'},
                    {'text': 'Show current page URL', 'is_correct': False, 'explanation': 'now tag is for current datetime display.'},
                    {'text': 'Display server uptime', 'is_correct': False, 'explanation': 'now tag shows current date and time.'}
                ]
            },
            {
                'text': 'Which Django management command opens an interactive Python shell?',
                'choices': [
                    {'text': 'python manage.py shell', 'is_correct': True, 'explanation': 'shell command opens Django-aware Python shell.'},
                    {'text': 'python manage.py console', 'is_correct': False, 'explanation': 'Django uses shell command for interactive console.'},
                    {'text': 'python manage.py interactive', 'is_correct': False, 'explanation': 'The correct command is shell.'},
                    {'text': 'python manage.py python', 'is_correct': False, 'explanation': 'Django uses shell command for Python console.'}
                ]
            },
            {
                'text': 'What is Django\'s {% regroup %} template tag used for?',
                'choices': [
                    {'text': 'Group objects by a common attribute', 'is_correct': True, 'explanation': 'regroup organizes objects by shared properties.'},
                    {'text': 'Reload template groups', 'is_correct': False, 'explanation': 'regroup organizes data by attributes.'},
                    {'text': 'Validate form groups', 'is_correct': False, 'explanation': 'regroup is for data organization in templates.'},
                    {'text': 'Create user groups', 'is_correct': False, 'explanation': 'regroup groups objects by common attributes.'}
                ]
            },
            {
                'text': 'Which Django setting controls media file serving?',
                'choices': [
                    {'text': 'MEDIA_URL and MEDIA_ROOT', 'is_correct': True, 'explanation': 'MEDIA_URL and MEDIA_ROOT handle uploaded files.'},
                    {'text': 'STATIC_URL and STATIC_ROOT', 'is_correct': False, 'explanation': 'STATIC settings are for static files, MEDIA for uploads.'},
                    {'text': 'FILE_URL and FILE_ROOT', 'is_correct': False, 'explanation': 'Django uses MEDIA_URL and MEDIA_ROOT.'},
                    {'text': 'UPLOAD_URL and UPLOAD_ROOT', 'is_correct': False, 'explanation': 'Django uses MEDIA settings for file uploads.'}
                ]
            },
            {
                'text': 'What is Django\'s {% cycle %} template tag used for?',
                'choices': [
                    {'text': 'Cycle through values in loops', 'is_correct': True, 'explanation': 'cycle alternates between values in iterations.'},
                    {'text': 'Create circular references', 'is_correct': False, 'explanation': 'cycle alternates values in loops.'},
                    {'text': 'Validate cyclic data', 'is_correct': False, 'explanation': 'cycle is for alternating values in templates.'},
                    {'text': 'Handle recursive templates', 'is_correct': False, 'explanation': 'cycle alternates through value lists.'}
                ]
            },
            {
                'text': 'Which Django field creates unique constraints?',
                'choices': [
                    {'text': 'Any field with unique=True', 'is_correct': True, 'explanation': 'unique=True creates database unique constraints.'},
                    {'text': 'UniqueField', 'is_correct': False, 'explanation': 'Django uses unique=True parameter on fields.'},
                    {'text': 'ConstraintField', 'is_correct': False, 'explanation': 'Use unique=True on any field type.'},
                    {'text': 'DistinctField', 'is_correct': False, 'explanation': 'Django uses unique=True for uniqueness.'}
                ]
            },
            {
                'text': 'What does Django\'s {% filter %} template tag do?',
                'choices': [
                    {'text': 'Apply template filters to content blocks', 'is_correct': True, 'explanation': 'filter tag applies filters to template sections.'},
                    {'text': 'Filter database queries', 'is_correct': False, 'explanation': 'filter tag applies template filters to content.'},
                    {'text': 'Validate user input', 'is_correct': False, 'explanation': 'filter tag is for template content filtering.'},
                    {'text': 'Sort template variables', 'is_correct': False, 'explanation': 'filter tag applies filters to content blocks.'}
                ]
            },
            {
                'text': 'Which Django command loads data from fixtures?',
                'choices': [
                    {'text': 'python manage.py loaddata', 'is_correct': True, 'explanation': 'loaddata imports data from fixture files.'},
                    {'text': 'python manage.py importdata', 'is_correct': False, 'explanation': 'Django uses loaddata for fixture imports.'},
                    {'text': 'python manage.py fixtures', 'is_correct': False, 'explanation': 'The correct command is loaddata.'},
                    {'text': 'python manage.py restore', 'is_correct': False, 'explanation': 'Django uses loaddata to load fixtures.'}
                ]
            },
            {
                'text': 'What is Django\'s Q object used for?',
                'choices': [
                    {'text': 'Complex database query conditions with AND/OR logic', 'is_correct': True, 'explanation': 'Q objects enable complex query combinations.'},
                    {'text': 'Queue background tasks', 'is_correct': False, 'explanation': 'Q objects are for database query logic.'},
                    {'text': 'Quality assurance testing', 'is_correct': False, 'explanation': 'Q objects create complex database queries.'},
                    {'text': 'Query result caching', 'is_correct': False, 'explanation': 'Q objects build complex query conditions.'}
                ]
            },
            {
                'text': 'Which Django decorator requires specific HTTP methods?',
                'choices': [
                    {'text': '@require_http_methods', 'is_correct': True, 'explanation': 'require_http_methods restricts allowed HTTP verbs.'},
                    {'text': '@http_methods', 'is_correct': False, 'explanation': 'Django uses @require_http_methods decorator.'},
                    {'text': '@allowed_methods', 'is_correct': False, 'explanation': 'The correct decorator is @require_http_methods.'},
                    {'text': '@method_required', 'is_correct': False, 'explanation': 'Django uses @require_http_methods.'}
                ]
            },
            {
                'text': 'What does Django\'s {% templatetag %} do?',
                'choices': [
                    {'text': 'Display template tag syntax literally', 'is_correct': True, 'explanation': 'templatetag shows template syntax without processing.'},
                    {'text': 'Create new template tags', 'is_correct': False, 'explanation': 'templatetag displays literal template syntax.'},
                    {'text': 'Load template libraries', 'is_correct': False, 'explanation': 'templatetag outputs literal template characters.'},
                    {'text': 'Validate template syntax', 'is_correct': False, 'explanation': 'templatetag displays template syntax literally.'}
                ]
            },
            {
                'text': 'Which Django field stores duration/time intervals?',
                'choices': [
                    {'text': 'DurationField', 'is_correct': True, 'explanation': 'DurationField stores time intervals and durations.'},
                    {'text': 'IntervalField', 'is_correct': False, 'explanation': 'Django uses DurationField for time intervals.'},
                    {'text': 'TimeDeltaField', 'is_correct': False, 'explanation': 'Django uses DurationField for durations.'},
                    {'text': 'PeriodField', 'is_correct': False, 'explanation': 'Django uses DurationField for time intervals.'}
                ]
            },
            {
                'text': 'What is Django\'s content types framework used for?',
                'choices': [
                    {'text': 'Generic relationships to any model type', 'is_correct': True, 'explanation': 'Content types enable relationships to any model.'},
                    {'text': 'MIME type validation', 'is_correct': False, 'explanation': 'Content types are for generic model relationships.'},
                    {'text': 'Content management', 'is_correct': False, 'explanation': 'Content types enable generic foreign keys.'},
                    {'text': 'File type detection', 'is_correct': False, 'explanation': 'Content types link to any model generically.'}
                ]
            },
            {
                'text': 'Which Django command creates data fixtures?',
                'choices': [
                    {'text': 'python manage.py dumpdata', 'is_correct': True, 'explanation': 'dumpdata exports database data to fixtures.'},
                    {'text': 'python manage.py exportdata', 'is_correct': False, 'explanation': 'Django uses dumpdata for data export.'},
                    {'text': 'python manage.py backup', 'is_correct': False, 'explanation': 'The correct command is dumpdata.'},
                    {'text': 'python manage.py savedata', 'is_correct': False, 'explanation': 'Django uses dumpdata to create fixtures.'}
                ]
            },
            {
                'text': 'What does Django\'s {% debug %} template tag do?',
                'choices': [
                    {'text': 'Display debugging information about template context', 'is_correct': True, 'explanation': 'debug tag shows template context variables.'},
                    {'text': 'Enable debug mode', 'is_correct': False, 'explanation': 'debug tag displays context information.'},
                    {'text': 'Log debug messages', 'is_correct': False, 'explanation': 'debug tag shows template debugging info.'},
                    {'text': 'Validate template syntax', 'is_correct': False, 'explanation': 'debug tag displays context variables.'}
                ]
            },
            {
                'text': 'Which Django field validates IP addresses?',
                'choices': [
                    {'text': 'GenericIPAddressField', 'is_correct': True, 'explanation': 'GenericIPAddressField validates IPv4 and IPv6.'},
                    {'text': 'IPField', 'is_correct': False, 'explanation': 'Django uses GenericIPAddressField for IPs.'},
                    {'text': 'AddressField', 'is_correct': False, 'explanation': 'Django uses GenericIPAddressField.'},
                    {'text': 'NetworkField', 'is_correct': False, 'explanation': 'Django uses GenericIPAddressField for IP validation.'}
                ]
            },
            {
                'text': 'What is Django\'s {% lorem %} template tag used for?',
                'choices': [
                    {'text': 'Generate placeholder Lorem Ipsum text', 'is_correct': True, 'explanation': 'lorem tag creates dummy text for templates.'},
                    {'text': 'Load remote content', 'is_correct': False, 'explanation': 'lorem generates placeholder text.'},
                    {'text': 'Format text content', 'is_correct': False, 'explanation': 'lorem creates Lorem Ipsum dummy text.'},
                    {'text': 'Validate text input', 'is_correct': False, 'explanation': 'lorem generates placeholder text content.'}
                ]
            },
            {
                'text': 'Which Django class handles file uploads?',
                'choices': [
                    {'text': 'UploadedFile', 'is_correct': True, 'explanation': 'UploadedFile represents uploaded file objects.'},
                    {'text': 'FileUpload', 'is_correct': False, 'explanation': 'Django uses UploadedFile for file uploads.'},
                    {'text': 'UploadHandler', 'is_correct': False, 'explanation': 'UploadedFile represents the uploaded file.'},
                    {'text': 'FileObject', 'is_correct': False, 'explanation': 'Django uses UploadedFile for uploaded files.'}
                ]
            },
            {
                'text': 'What does Django\'s {% verbatim %} template tag do?',
                'choices': [
                    {'text': 'Prevent template tag processing in content', 'is_correct': True, 'explanation': 'verbatim stops template processing for literal output.'},
                    {'text': 'Display verbose error messages', 'is_correct': False, 'explanation': 'verbatim prevents template tag processing.'},
                    {'text': 'Enable verbose logging', 'is_correct': False, 'explanation': 'verbatim outputs content literally.'},
                    {'text': 'Validate template verbosity', 'is_correct': False, 'explanation': 'verbatim prevents template tag interpretation.'}
                ]
            },
            {
                'text': 'Which Django setting controls timezone handling?',
                'choices': [
                    {'text': 'USE_TZ and TIME_ZONE', 'is_correct': True, 'explanation': 'USE_TZ enables timezone support, TIME_ZONE sets default.'},
                    {'text': 'TIMEZONE_ENABLED', 'is_correct': False, 'explanation': 'Django uses USE_TZ and TIME_ZONE settings.'},
                    {'text': 'DATETIME_FORMAT', 'is_correct': False, 'explanation': 'USE_TZ and TIME_ZONE control timezone behavior.'},
                    {'text': 'TIMEZONE_CONFIG', 'is_correct': False, 'explanation': 'Django uses USE_TZ and TIME_ZONE for timezones.'}
                ]
            },
            {
                'text': 'What is Django\'s {% widthratio %} template tag used for?',
                'choices': [
                    {'text': 'Calculate proportional values for width/height', 'is_correct': True, 'explanation': 'widthratio calculates proportional measurements.'},
                    {'text': 'Set image aspect ratios', 'is_correct': False, 'explanation': 'widthratio calculates proportional values.'},
                    {'text': 'Validate width measurements', 'is_correct': False, 'explanation': 'widthratio computes proportional calculations.'},
                    {'text': 'Format ratio displays', 'is_correct': False, 'explanation': 'widthratio calculates proportional values.'}
                ]
            },
            {
                'text': 'Which Django command shows installed packages?',
                'choices': [
                    {'text': 'pip list (not a Django command)', 'is_correct': True, 'explanation': 'pip list shows installed packages, not manage.py.'},
                    {'text': 'python manage.py packages', 'is_correct': False, 'explanation': 'Use pip list to see installed packages.'},
                    {'text': 'python manage.py listpackages', 'is_correct': False, 'explanation': 'pip list shows installed packages.'},
                    {'text': 'python manage.py installed', 'is_correct': False, 'explanation': 'pip list is the correct command for packages.'}
                ]
            },
            {
                'text': 'What does Django\'s F() expression do?',
                'choices': [
                    {'text': 'Reference model field values in database operations', 'is_correct': True, 'explanation': 'F() expressions reference fields in DB operations.'},
                    {'text': 'Create function-based views', 'is_correct': False, 'explanation': 'F() expressions reference model fields.'},
                    {'text': 'Format output values', 'is_correct': False, 'explanation': 'F() expressions work with database field values.'},
                    {'text': 'Filter query results', 'is_correct': False, 'explanation': 'F() expressions reference field values in queries.'}
                ]
            },
            {
                'text': 'Which Django field stores UUID values?',
                'choices': [
                    {'text': 'UUIDField', 'is_correct': True, 'explanation': 'UUIDField stores UUID primary keys and identifiers.'},
                    {'text': 'CharField', 'is_correct': False, 'explanation': 'UUIDField is specifically for UUID values.'},
                    {'text': 'IdentifierField', 'is_correct': False, 'explanation': 'Django uses UUIDField for UUID storage.'},
                    {'text': 'UniqueIDField', 'is_correct': False, 'explanation': 'Django uses UUIDField for UUID values.'}
                ]
            }
        ]

        created_count = 0
        for question_data in questions_data:
            # Create question
            question = Question.objects.create(
                text=question_data['text'],
                category=django_category,
                time_limit=30  # Default 30 seconds
            )
            
            # Create choices for this question
            for choice_data in question_data['choices']:
                Choice.objects.create(
                    question=question,
                    text=choice_data['text'],
                    is_correct=choice_data['is_correct'],
                    explanation=choice_data.get('explanation', '')
                )
            
            created_count += 1
            
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {created_count} unique Django questions with 4 choices each!'
            )
        )