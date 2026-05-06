from django.shortcuts import render
from jobs.models import Job
from machine.models import MachineLog


def index(request):
    recent_jobs = Job.objects.order_by('-created_at')[:5]
    logs = MachineLog.objects.order_by('-timestamp')[:10]
    return render(request, 'dashboard/index.html', {
        'recent_jobs': recent_jobs,
        'logs': logs,
    })
