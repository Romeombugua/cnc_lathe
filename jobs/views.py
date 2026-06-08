import json

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

from .models import Job
from machine.models import MachineConfig, MachineLog
from gpt_engine.gpt_client import generate_gcode
from gpt_engine.validator import validate_gcode
from serial_comm.controller import serial_controller


def command(request):
    return render(request, 'jobs/command.html')


@require_POST
def generate(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid request body'})

    command_text = body.get('command', '').strip()
    if not command_text:
        return JsonResponse({'success': False, 'message': 'Command text is required'})

    config = MachineConfig.get_config()
    if not config.api_key:
        return JsonResponse({
            'success': False,
            'message': 'OpenAI API key not configured — please go to Settings.',
        })

    try:
        gcode = generate_gcode(
            command=command_text,
            api_key=config.api_key,
            model=config.api_model,
            x_limit=config.x_limit,
            y_limit=config.z_limit,
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'message': str(exc)})
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'GPT error: {exc}'})

    if not gcode.strip():
        return JsonResponse({'success': False, 'message': 'GPT returned empty G-code. Try rephrasing the command.'})

    job = Job.objects.create(
        command=command_text,
        generated_gcode=gcode,
        execution_status='pending',
    )

    return JsonResponse({'success': True, 'gcode': gcode, 'job_id': job.id})


@require_POST
def validate(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'valid': False, 'errors': ['Invalid request'], 'warnings': [], 'line_count': 0})

    gcode = body.get('gcode', '')
    config = MachineConfig.get_config()
    result = validate_gcode(gcode, x_limit=config.x_limit, y_limit=config.z_limit)
    return JsonResponse(result)


@require_POST
def execute(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid request body'})

    gcode = body.get('gcode', '').strip()
    job_id = body.get('job_id')
    command_text = body.get('command', '').strip()

    if not gcode:
        return JsonResponse({'success': False, 'message': 'No G-code provided'})

    config = MachineConfig.get_config()

    # Validate before sending to hardware
    validation = validate_gcode(gcode, x_limit=config.x_limit, y_limit=config.z_limit)
    if not validation['valid']:
        return JsonResponse({
            'success': False,
            'message': 'Validation failed: ' + '; '.join(validation['errors']),
        })

    # Retrieve or create Job record
    job = None
    if job_id:
        try:
            job = Job.objects.get(id=job_id)
            job.generated_gcode = gcode
            job.execution_status = 'running'
            job.error_message = ''
            job.save()
        except Job.DoesNotExist:
            job = None

    if job is None:
        job = Job.objects.create(
            command=command_text,
            generated_gcode=gcode,
            execution_status='running',
        )

    success, message = serial_controller.send_gcode(gcode.splitlines(), job_id=job.id)

    if not success:
        job.execution_status = 'failed'
        job.error_message = message
        job.save()
        MachineLog.objects.create(event_type='job_error', message=message)
        return JsonResponse({'success': False, 'message': message})

    MachineLog.objects.create(
        event_type='job_start',
        message=f'Job #{job.id} started — {command_text[:60]}',
    )
    return JsonResponse({'success': True, 'job_id': job.id, 'message': message})


def history(request):
    jobs = Job.objects.all()
    return render(request, 'jobs/history.html', {'jobs': jobs})


def cycle(request):
    """Cycle control page merged into dashboard — redirect to keep old URL working."""
    from django.shortcuts import redirect
    return redirect('dashboard:index')


@require_POST
def generate_profile(request):
    """Phase IV: generate deterministic multi-pass G-code from profile parameters."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid request body'})

    try:
        d_stock = float(body['d_stock'])
        l_stickout = float(body['l_stickout'])
        d_target = float(body['d_target'])
        l_cut = float(body['l_cut'])
    except (KeyError, ValueError, TypeError) as exc:
        return JsonResponse({'success': False, 'message': f'Invalid parameter: {exc}'})

    # Strict input validation per spec §4.1
    errors = []
    if not (1.0 <= d_stock <= 185.0):
        errors.append('D_stock must be 1–185 mm')
    if not (1.0 <= l_stickout <= 110.0):
        errors.append('L_stickout must be 1–110 mm')
    if not (0.5 <= d_target <= d_stock - 0.5):
        errors.append(f'D_target must be 0.5–{d_stock - 0.5:.1f} mm')
    if not (0.5 <= l_cut <= l_stickout - 0.5):
        errors.append(f'L_cut must be 0.5–{l_stickout - 0.5:.1f} mm')
    if errors:
        return JsonResponse({'success': False, 'message': '; '.join(errors)})

    config = MachineConfig.get_config()
    if not config.api_key:
        return JsonResponse({
            'success': False,
            'message': 'OpenAI API key not configured — please go to Settings.',
        })

    try:
        from gpt_engine.gpt_client import generate_gcode_from_profile
        gcode = generate_gcode_from_profile(
            d_stock=d_stock,
            l_stickout=l_stickout,
            d_target=d_target,
            l_cut=l_cut,
            api_key=config.api_key,
            model=config.api_model,
            x_limit=config.x_limit,
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'message': str(exc)})
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'GPT error: {exc}'})

    job = Job.objects.create(
        command=(
            f'Profile turn: Ø{d_stock}→{d_target} mm, '
            f'L_stickout={l_stickout} mm, L_cut={l_cut} mm'
        ),
        generated_gcode=gcode,
        execution_status='pending',
    )
    return JsonResponse({'success': True, 'gcode': gcode, 'job_id': job.id})


@require_GET
def job_detail(request, job_id):
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)

    return JsonResponse({
        'id': job.id,
        'command': job.command,
        'generated_gcode': job.generated_gcode,
        'execution_status': job.execution_status,
        'created_at': job.created_at.isoformat(),
        'error_message': job.error_message,
    })
