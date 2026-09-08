from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('verify/<str:uidb64>/<str:token>/', views.verify_email, name='verify_email'),
    path('resend-verification/', views.resend_verification, name='resend_verification'),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='quiz/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
    
    # Custom Password reset URLs using SRMIST verification
    path('accounts/password_reset/', views.custom_password_reset, name='password_reset'),
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='quiz/password_reset_done.html'
    ), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', views.custom_password_reset_confirm, name='password_reset_confirm'),
    path('accounts/reset/done/', views.password_reset_complete, name='password_reset_complete'),
    path('anti-cheat-warning/<int:category_id>/', views.anti_cheat_warning, name='anti_cheat_warning'),
    path('start/<int:category_id>/', views.start_quiz, name='start_quiz'),
    path('results/<int:category_id>/', views.view_results, name='view_results'),
    path('review/<int:category_id>/', views.quiz_review, name='quiz_review'),
    path('leaderboard/', views.leaderboard, name='leaderboard'),
    path('profile/', views.user_profile, name='user_profile'),
    path('question/', views.question_view, name='question'),
    path('result/', views.result, name='result'),
    path('already/', views.already_taken, name='already_taken'),
]
