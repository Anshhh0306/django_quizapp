import random
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from quiz.models import Category, Question, Choice, UserQuiz, UserAnswer, UserStatistics

class Command(BaseCommand):
    help = 'Create 20 random users and simulate quiz attempts for testing'

    def handle(self, *args, **options):
        # Sample usernames and data
        usernames = [
            'student001', 'coder_alex', 'quiz_master', 'dev_sarah', 'tech_guru',
            'python_pro', 'web_wizard', 'data_ninja', 'code_warrior', 'debug_queen',
            'script_king', 'byte_crusher', 'logic_lord', 'syntax_sage', 'algo_ace',
            'function_fan', 'loop_legend', 'variable_victor', 'class_champion', 'method_master'
        ]
        
        first_names = [
            'Alex', 'Sarah', 'Mike', 'Emma', 'David', 'Lisa', 'John', 'Amy',
            'Chris', 'Maria', 'Ryan', 'Jessica', 'Tom', 'Anna', 'Kevin',
            'Rachel', 'Mark', 'Sophia', 'Daniel', 'Olivia'
        ]
        
        last_names = [
            'Smith', 'Johnson', 'Brown', 'Davis', 'Miller', 'Wilson', 'Moore',
            'Taylor', 'Anderson', 'Thomas', 'Jackson', 'White', 'Harris',
            'Martin', 'Thompson', 'Garcia', 'Martinez', 'Robinson', 'Clark', 'Rodriguez'
        ]

        self.stdout.write('Creating 20 random users...')
        
        created_users = []
        
        for i in range(20):
            username = usernames[i]
            first_name = first_names[i]
            last_name = last_names[i]
            email = f"{username}@example.com"
            
            # Create user (skip email verification for test users)
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'is_active': True,  # Skip email verification
                }
            )
            
            if created:
                user.set_password('testpass123')
                user.save()
                created_users.append(user)
                self.stdout.write(f'✓ Created user: {username}')
            else:
                created_users.append(user)
                self.stdout.write(f'→ User already exists: {username}')

        self.stdout.write('\nSimulating quiz attempts...')
        
        # Get all categories and questions
        categories = Category.objects.all()
        
        if not categories.exists():
            self.stdout.write(self.style.ERROR('No categories found! Please add some quiz categories first.'))
            return
            
        # Simulate quiz attempts for each user
        for user in created_users:
            num_quizzes = random.randint(1, 5)  # Each user takes 1-5 quizzes
            
            for _ in range(num_quizzes):
                category = random.choice(categories)
                questions = list(Question.objects.filter(category=category))
                
                if not questions:
                    continue
                    
                # Create UserQuiz
                user_quiz, created = UserQuiz.objects.get_or_create(
                    user=user,
                    category=category,
                    defaults={
                        'completed': True,
                        'total_questions': len(questions),
                        'total_points': len(questions),  # Assuming 1 point per question
                        'taken_on': timezone.now() - timezone.timedelta(days=random.randint(0, 30)),
                        'average_time_per_question': random.uniform(10, 30)
                    }
                )
                
                if not created:
                    continue  # User already took this category
                
                correct_answers = 0
                
                # Simulate answers for each question
                for question in questions:
                    choices = list(question.choices.all())
                    if not choices:
                        continue
                        
                    # 70% chance of getting it right (to make leaderboard interesting)
                    if random.random() < 0.7:
                        # Select correct answer
                        correct_choice = next((c for c in choices if c.is_correct), None)
                        selected_choice = correct_choice
                        is_correct = True if correct_choice else False
                    else:
                        # Select wrong answer
                        wrong_choices = [c for c in choices if not c.is_correct]
                        selected_choice = random.choice(wrong_choices) if wrong_choices else choices[0]
                        is_correct = False
                    
                    if is_correct:
                        correct_answers += 1
                    
                    # Create UserAnswer
                    UserAnswer.objects.get_or_create(
                        user_quiz=user_quiz,
                        question=question,
                        defaults={
                            'selected_choice': selected_choice,
                            'is_correct': is_correct,
                            'time_taken': random.uniform(5, 25)
                        }
                    )
                
                # Update quiz score
                user_quiz.score = correct_answers
                user_quiz.save()
                
                self.stdout.write(f'  → {user.username} completed {category.name}: {correct_answers}/{len(questions)}')
        
        self.stdout.write('\nUpdating user statistics...')
        
        # Update all user statistics
        for user in created_users:
            stats, created = UserStatistics.objects.get_or_create(user=user)
            stats.update_stats()
            self.stdout.write(f'  → Updated stats for {user.username}')
        
        self.stdout.write(self.style.SUCCESS('\n🎉 Successfully created 20 users with random quiz data!'))
        self.stdout.write(self.style.SUCCESS('Now you can test:'))
        self.stdout.write('  • Leaderboard with real competition')
        self.stdout.write('  • Admin panel user management')
        self.stdout.write('  • Tied scores dropdown functionality')
        self.stdout.write('  • User profiles with varied performance')
        self.stdout.write('\nAll test users have password: testpass123')