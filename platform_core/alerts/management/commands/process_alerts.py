"""
Process Alert Rules Command
"""
from django.core.management.base import BaseCommand
from platform_core.alerts.services import AlertManager


class Command(BaseCommand):
    help = 'Process alert rules and send notifications'
    
    def handle(self, *args, **options):
        self.stdout.write('Processing alert rules...')
        
        try:
            manager = AlertManager()
            manager.process_alerts()
            
            self.stdout.write(self.style.SUCCESS('Alert processing completed'))
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Alert processing failed: {e}')
            )