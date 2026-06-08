from django.urls import path
from . import views

app_name = 'jobs'

urlpatterns = [
    path('command/', views.command, name='command'),
    path('generate/', views.generate, name='generate'),
    path('validate/', views.validate, name='validate'),
    path('execute/', views.execute, name='execute'),
    path('history/', views.history, name='history'),
    path('<int:job_id>/detail/', views.job_detail, name='job_detail'),
    path('cycle/', views.cycle, name='cycle'),
    path('generate-profile/', views.generate_profile, name='generate_profile'),
]
