from django.contrib import admin
from .models import MachineConfig, MachineLog


@admin.register(MachineConfig)
class MachineConfigAdmin(admin.ModelAdmin):
    list_display = ['x_limit', 'z_limit', 'baud_rate', 'com_port', 'api_model']


@admin.register(MachineLog)
class MachineLogAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'message', 'timestamp']
    list_filter = ['event_type']
    readonly_fields = ['timestamp']
