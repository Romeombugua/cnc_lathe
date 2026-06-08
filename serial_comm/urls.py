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
    path('jog/', views.jog, name='jog'),
    path('set-origin/', views.set_work_origin, name='set_work_origin'),
]
