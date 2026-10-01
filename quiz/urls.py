from django.urls import path
from . import views, teacher_views, exam_views, exam_take
from .forms import LoginForm
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('verify/<str:uidb64>/<str:token>/', views.verify_email, name='verify_email'),
    path('resend-verification/', views.resend_verification, name='resend_verification'),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='quiz/login.html', authentication_form=LoginForm), name='login'),
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

    # Teacher tools and exam links
    path('teach/', teacher_views.teach_home, name='teach_home'),
    path('teach/questions/', teacher_views.question_bank, name='question_bank'),
    path('teach/templates/questions.csv', teacher_views.question_template, name='question_template'),
    path('teach/templates/students.csv', teacher_views.student_template, name='student_template'),
    path('teach/exams/new/', teacher_views.exam_new, name='exam_new'),
    path('teach/exams/<int:pk>/', teacher_views.exam_detail, name='exam_detail'),
    path('teach/exams/<int:pk>/live/', teacher_views.exam_live, name='exam_live'),
    path('teach/exams/<int:pk>/results/', teacher_views.exam_results, name='exam_results'),
    path('teach/exams/<int:pk>/results/<int:attempt_pk>/', teacher_views.exam_result_detail, name='exam_result_detail'),
    path('exam/<str:token>/', exam_views.exam_entry, name='exam_entry'),
    path('exam/<str:token>/consent/', exam_views.exam_consent, name='exam_consent'),
    path('exam/<str:token>/lobby/', exam_views.exam_lobby, name='exam_lobby'),
    path('exam/<str:token>/status/', exam_views.exam_status, name='exam_status'),
    path('exam/<str:token>/take/', exam_take.exam_take, name='exam_take'),
    path('exam/<str:token>/answer/', exam_take.exam_answer, name='exam_answer'),
    path('exam/<str:token>/submit/', exam_take.exam_submit, name='exam_submit'),
    path('exam/<str:token>/done/', exam_take.exam_done, name='exam_done'),
]
