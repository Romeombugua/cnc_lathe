from django.db import models


class MachineConfig(models.Model):
    x_limit = models.FloatField(default=100.0)
    z_limit = models.FloatField(default=200.0)
    baud_rate = models.IntegerField(default=115200)
    com_port = models.CharField(max_length=20, default='COM3')
    api_key = models.CharField(max_length=300, blank=True)
    api_model = models.CharField(max_length=50, default='gpt-5')

    class Meta:
        verbose_name = 'Machine Configuration'

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(id=1)
        return config

    def __str__(self):
        return f'Machine Config (X:{self.x_limit}mm, Z:{self.z_limit}mm)'


class MachineLog(models.Model):
    EVENT_CHOICES = [
        ('connection', 'Connection'),
        ('disconnection', 'Disconnection'),
        ('job_start', 'Job Start'),
        ('job_complete', 'Job Complete'),
        ('job_error', 'Job Error'),
        ('emergency_stop', 'Emergency Stop'),
        ('validation_error', 'Validation Error'),
    ]
    event_type = models.CharField(max_length=50, choices=EVENT_CHOICES)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.event_type}: {self.message[:50]}'
