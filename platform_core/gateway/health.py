"""
Health Check Service

Monitors health of backend services.
"""

import logging
import asyncio
import aiohttp
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction

from .models import ServiceRegistry, ServiceInstance

logger = logging.getLogger(__name__)


class HealthChecker:
    """
    Performs health checks on registered services.
    """
    
    def __init__(self):
        self.session = None
        self.running = False
    
    async def start(self):
        """Start health checking"""
        if self.running:
            return
        
        self.running = True
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        
        # Start health check tasks
        tasks = []
        services = ServiceRegistry.objects.filter(
            is_active=True,
            health_check_enabled=True
        )
        
        for service in services:
            task = asyncio.create_task(self._health_check_loop(service))
            tasks.append(task)
        
        # Keep tasks running
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Health checker error: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop health checking"""
        self.running = False
        if self.session:
            await self.session.close()
    
    async def _health_check_loop(self, service: ServiceRegistry):
        """Health check loop for a service"""
        while self.running:
            try:
                # Perform health check
                is_healthy = await self._check_service_health(service)
                
                # Update service status
                with transaction.atomic():
                    service.is_healthy = is_healthy
                    service.last_health_check = timezone.now()
                    service.save(update_fields=['is_healthy', 'last_health_check'])
                    
                    # Update instances if any
                    if hasattr(service, 'instances'):
                        for instance in service.instances.all():
                            instance_healthy = await self._check_instance_health(
                                instance
                            )
                            instance.is_healthy = instance_healthy
                            instance.last_health_check = timezone.now()
                            
                            if not instance_healthy:
                                instance.health_check_failures += 1
                            else:
                                instance.health_check_failures = 0
                            
                            instance.save(update_fields=[
                                'is_healthy',
                                'last_health_check',
                                'health_check_failures'
                            ])
                
                # Log status change
                if is_healthy != service.is_healthy:
                    logger.info(
                        f"Service {service.name} health changed to {is_healthy}"
                    )
                
            except Exception as e:
                logger.error(f"Health check failed for {service.name}: {e}")
            
            # Wait for next check
            await asyncio.sleep(service.health_check_interval)
    
    async def _check_service_health(self, service: ServiceRegistry) -> bool:
        """
        Check health of a service.
        
        Args:
            service: Service to check
            
        Returns:
            True if healthy
        """
        if service.health_check_type == 'http':
            return await self._http_health_check(
                service.get_full_url(service.health_check_path)
            )
        elif service.health_check_type == 'tcp':
            return await self._tcp_health_check(
                service.base_url
            )
        elif service.health_check_type == 'custom':
            # Custom health check logic would go here
            return True
        
        return True
    
    async def _check_instance_health(self, instance: ServiceInstance) -> bool:
        """Check health of a service instance"""
        service = instance.service
        
        if service.health_check_type == 'http':
            url = f"{instance.get_url()}{service.health_check_path}"
            return await self._http_health_check(url)
        elif service.health_check_type == 'tcp':
            return await self._tcp_health_check(
                instance.host,
                instance.port
            )
        
        return True
    
    async def _http_health_check(self, url: str) -> bool:
        """
        Perform HTTP health check.
        
        Args:
            url: Health check URL
            
        Returns:
            True if healthy (2xx response)
        """
        try:
            async with self.session.get(url) as response:
                return 200 <= response.status < 300
        except Exception as e:
            logger.debug(f"HTTP health check failed for {url}: {e}")
            return False
    
    async def _tcp_health_check(self, host: str, port: int = None) -> bool:
        """
        Perform TCP health check.
        
        Args:
            host: Host to check (or full URL)
            port: Port number
            
        Returns:
            True if can connect
        """
        try:
            # Parse URL if needed
            if host.startswith('http'):
                from urllib.parse import urlparse
                parsed = urlparse(host)
                host = parsed.hostname
                port = port or parsed.port or (443 if parsed.scheme == 'https' else 80)
            
            # Try to connect
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return True
            
        except Exception as e:
            logger.debug(f"TCP health check failed for {host}:{port}: {e}")
            return False


class HealthMonitor:
    """
    Monitors service health and triggers alerts.
    """
    
    def __init__(self):
        self.thresholds = {
            'consecutive_failures': 3,
            'failure_rate': 0.5,
            'response_time': 5000,  # ms
        }
    
    def check_alerts(self):
        """Check for services that need alerts"""
        unhealthy_services = []
        
        # Check for unhealthy services
        services = ServiceRegistry.objects.filter(
            is_active=True,
            is_healthy=False
        )
        
        for service in services:
            # Check how long it's been unhealthy
            if service.last_health_check:
                duration = timezone.now() - service.last_health_check
                if duration > timedelta(minutes=5):
                    unhealthy_services.append({
                        'service': service,
                        'reason': 'prolonged_outage',
                        'duration': duration
                    })
        
        # Check for high failure rates
        for service in ServiceRegistry.objects.filter(is_active=True):
            instances = service.instances.all()
            if instances:
                failed = sum(1 for i in instances if not i.is_healthy)
                if failed / len(instances) >= self.thresholds['failure_rate']:
                    unhealthy_services.append({
                        'service': service,
                        'reason': 'high_failure_rate',
                        'rate': failed / len(instances)
                    })
        
        return unhealthy_services
    
    def send_alerts(self, unhealthy_services: List[Dict]):
        """Send alerts for unhealthy services"""
        from platform_core.notifications.services import NotificationService
        
        notification_service = NotificationService()
        
        for alert in unhealthy_services:
            service = alert['service']
            reason = alert['reason']
            
            # Build alert message
            if reason == 'prolonged_outage':
                message = (
                    f"Service {service.display_name} has been down for "
                    f"{alert['duration'].total_seconds() / 60:.0f} minutes"
                )
            elif reason == 'high_failure_rate':
                message = (
                    f"Service {service.display_name} has {alert['rate']:.0%} "
                    f"of instances failing"
                )
            else:
                message = f"Service {service.display_name} is unhealthy"
            
            # Send notification
            notification_service.send_notification(
                'service_health_alert',
                {
                    'service': service.name,
                    'message': message,
                    'severity': 'high'
                }
            )


# Singleton instance
_health_checker = None


def get_health_checker() -> HealthChecker:
    """Get health checker instance"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker