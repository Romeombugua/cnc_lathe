from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import MachineConfig, MachineLog
from serial_comm.controller import serial_controller

BAUD_RATES = [9600, 19200, 38400, 57600, 115200]


def settings_view(request):
    config = MachineConfig.get_config()

    if request.method == 'POST':
        config.api_key = request.POST.get('api_key', '').strip()
        config.api_model = request.POST.get('api_model', 'gpt-4o').strip()
        config.com_port = request.POST.get('com_port', 'COM3').strip()
        try:
            config.baud_rate = int(request.POST.get('baud_rate', 115200))
            config.x_limit = float(request.POST.get('x_limit', 100.0))
            config.z_limit = float(request.POST.get('z_limit', 200.0))
        except ValueError:
            messages.error(request, 'Invalid numeric value in settings.')
            return redirect('machine:settings')

        config.save()
        messages.success(request, 'Settings saved successfully.')
        return redirect('machine:settings')

    return render(request, 'machine/settings.html', {
        'config': config,
        'baud_rates': BAUD_RATES,
    })


@require_GET
def status_view(request):
    return JsonResponse(serial_controller.get_status())
