from django.urls import path
from . import views

app_name = 'serial'

urlpatterns = [
    path('connect/', views.connect, name='connect'),
    path('disconnect/', views.disconnect, name='disconnect'),
    path('emergency-stop/', views.emergency_stop, name='emergency_stop'),
    path('ports/', views.ports, name='ports'),
    path('home/', views.home, name='home'),
    path('sync/', views.sync, name='sync'),
    path('dry-run/', views.set_dry_run, name='set_dry_run'),
    path('cancel-job/', views.cancel_job, name='cancel_job'),
]
