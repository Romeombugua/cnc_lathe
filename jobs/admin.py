from django.contrib import admin
from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ['id', 'command', 'execution_status', 'created_at']
    list_filter = ['execution_status']
    readonly_fields = ['created_at', 'completed_at']
