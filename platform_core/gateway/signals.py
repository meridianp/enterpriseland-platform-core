"""
Gateway Signals

Signals for gateway events and notifications.
"""

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver, Signal

from .models import ServiceRegistry, Route, ServiceInstance
from .router import ServiceRouter

# Custom signals
service_health_changed = Signal()  # providing_args=['service', 'is_healthy']
route_activated = Signal()  # providing_args=['route']
route_deactivated = Signal()  # providing_args=['route']
circuit_breaker_opened = Signal()  # providing_args=['service']
circuit_breaker_closed = Signal()  # providing_args=['service']


@receiver(post_save, sender=ServiceRegistry)
def handle_service_save(sender, instance, created, **kwargs):
    """Handle service save"""
    if created:
        # Log new service registration
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"New service registered: {instance.name}")
    
    # Clear router cache when service changes
    router = ServiceRouter()
    router.clear_cache()
    
    # Check if health status changed
    if not created and 'is_healthy' in kwargs.get('update_fields', []):
        service_health_changed.send(
            sender=ServiceRegistry,
            service=instance,
            is_healthy=instance.is_healthy
        )


@receiver(pre_delete, sender=ServiceRegistry)
def handle_service_delete(sender, instance, **kwargs):
    """Handle service deletion"""
    # Deactivate all routes for this service
    Route.objects.filter(service=instance).update(is_active=False)
    
    # Clear router cache
    router = ServiceRouter()
    router.clear_cache()


@receiver(post_save, sender=Route)
def handle_route_save(sender, instance, created, **kwargs):
    """Handle route save"""
    # Clear router cache when route changes
    router = ServiceRouter()
    router.clear_cache()
    
    # Send signals for activation changes
    if not created and 'is_active' in kwargs.get('update_fields', []):
        if instance.is_active:
            route_activated.send(sender=Route, route=instance)
        else:
            route_deactivated.send(sender=Route, route=instance)


@receiver(post_save, sender=ServiceInstance)
def handle_instance_save(sender, instance, created, **kwargs):
    """Handle instance save"""
    if not created and 'is_healthy' in kwargs.get('update_fields', []):
        # Check if all instances are unhealthy
        service = instance.service
        healthy_count = service.instances.filter(is_healthy=True).count()
        
        if healthy_count == 0 and service.is_healthy:
            # Mark service as unhealthy
            service.is_healthy = False
            service.save(update_fields=['is_healthy'])
        elif healthy_count > 0 and not service.is_healthy:
            # Mark service as healthy
            service.is_healthy = True
            service.save(update_fields=['is_healthy'])


# Signal handlers for monitoring
@receiver(service_health_changed)
def notify_health_change(sender, service, is_healthy, **kwargs):
    """Notify when service health changes"""
    from platform_core.notifications.services import NotificationService
    
    notification_service = NotificationService()
    
    if is_healthy:
        message = f"Service {service.display_name} is now healthy"
        severity = 'info'
    else:
        message = f"Service {service.display_name} is now unhealthy"
        severity = 'high'
    
    notification_service.send_notification(
        'service_health_change',
        {
            'service': service.name,
            'message': message,
            'severity': severity,
            'is_healthy': is_healthy
        }
    )


@receiver(circuit_breaker_opened)
def notify_circuit_opened(sender, service, **kwargs):
    """Notify when circuit breaker opens"""
    from platform_core.notifications.services import NotificationService
    
    notification_service = NotificationService()
    notification_service.send_notification(
        'circuit_breaker_opened',
        {
            'service': service.name,
            'message': f"Circuit breaker opened for {service.display_name}",
            'severity': 'high'
        }
    )