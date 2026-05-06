from django.urls import path
from . import views

app_name = 'machine'

urlpatterns = [
    path('settings/', views.settings_view, name='settings'),
    path('status/', views.status_view, name='status'),
]
