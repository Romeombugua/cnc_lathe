import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt

from .controller import serial_controller
from machine.models import MachineConfig, MachineLog


@csrf_exempt
@require_POST
def connect(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid request body'})

    port = body.get('port', '').strip()
    try:
        baud_rate = int(body.get('baud_rate', 115200))
    except (ValueError, TypeError):
        baud_rate = 115200

    if not port:
        return JsonResponse({'success': False, 'message': 'COM port is required'})

    success, message = serial_controller.connect(port, baud_rate)

    if success:
        MachineLog.objects.create(
            event_type='connection',
            message=f'Connected to {port} at {baud_rate} baud',
        )

    return JsonResponse({'success': success, 'message': message})


@csrf_exempt
@require_POST
def disconnect(request):
    success, message = serial_controller.disconnect()
    if success:
        MachineLog.objects.create(
            event_type='disconnection',
            message='Disconnected from machine',
        )
    return JsonResponse({'success': success, 'message': message})


@csrf_exempt
@require_POST
def emergency_stop(request):
    serial_controller.emergency_stop()
    MachineLog.objects.create(
        event_type='emergency_stop',
        message='Emergency stop activated by user',
    )
    return JsonResponse({'success': True, 'message': 'Emergency stop activated'})


@require_GET
def ports(request):
    available = serial_controller.get_available_ports()
    config = MachineConfig.get_config()
    return JsonResponse({
        'ports': available,
        'default_port': config.com_port,
    })


@csrf_exempt
@require_POST
def home(request):
    """Phase I: trigger GRBL homing cycle ($H)."""
    success, message = serial_controller.home()
    if success:
        MachineLog.objects.create(
            event_type='connection',
            message='Homing cycle initiated',
        )
    return JsonResponse({'success': success, 'message': message})


@csrf_exempt
@require_POST
def sync(request):
    """Phase II+III: set G54 work offset and move to safe staging position."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid request body'})
    try:
        l_stickout = float(body.get('l_stickout', 0))
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Invalid l_stickout value'})
    if not (1.0 <= l_stickout <= 110.0):
        return JsonResponse({'success': False, 'message': 'L_stickout must be 1–110 mm'})
    success, message = serial_controller.sync_workpiece(l_stickout)
    return JsonResponse({'success': success, 'message': message})


@csrf_exempt
@require_POST
def set_dry_run(request):
    """Toggle dry-run mode (spindle suppression)."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid request body'})
    enabled = bool(body.get('enabled', True))
    serial_controller.set_dry_run(enabled)
    return JsonResponse({'success': True, 'dry_run': enabled})


@csrf_exempt
@require_POST
def cancel_job(request):
    """Cancel the currently running job and reset controller to idle."""
    success, message = serial_controller.cancel_job()
    if success:
        MachineLog.objects.create(
            event_type='job_error',
            message='Job cancelled by operator',
        )
    return JsonResponse({'success': success, 'message': message})
