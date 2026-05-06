from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),
    path('jobs/', include('jobs.urls')),
    path('machine/', include('machine.urls')),
    path('serial/', include('serial_comm.urls')),
]
