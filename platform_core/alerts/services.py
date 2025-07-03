"""
Alert Management Services
"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache

from .models import Alert, AlertRule, AlertChannel, AlertStatus, AlertSilence
from .channels import get_channel_class
from ..monitoring.metrics import MetricsRegistry

logger = logging.getLogger(__name__)


class AlertProcessor:
    """Process and evaluate alerts"""
    
    def __init__(self):
        self.metrics_registry = MetricsRegistry()
    
    def evaluate_rules(self) -> List[Alert]:
        """Evaluate all active alert rules"""
        alerts_created = []
        
        for rule in AlertRule.objects.filter(enabled=True):
            try:
                alert = self._evaluate_rule(rule)
                if alert:
                    alerts_created.append(alert)
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name}: {e}")
        
        return alerts_created
    
    def _evaluate_rule(self, rule: AlertRule) -> Optional[Alert]:
        """Evaluate a single rule"""
        # Get metric value
        metric = self.metrics_registry.get_metric(rule.metric_name)
        if not metric:
            logger.warning(f"Metric {rule.metric_name} not found for rule {rule.name}")
            return None
        
        # Get current value
        value = metric.value
        if hasattr(metric, 'get_value'):
            value = metric.get_value()
        
        # Check if condition is met
        if not rule.evaluate(value):
            # Check if there's an active alert to resolve
            self._resolve_alerts(rule)
            return None
        
        # Check if we need to wait for duration
        cache_key = f"alert_rule_{rule.id}_pending"
        pending_since = cache.get(cache_key)
        
        if not pending_since:
            # First time condition is true
            cache.set(cache_key, timezone.now(), rule.for_duration)
            return None
        
        # Check if duration has passed
        if (timezone.now() - pending_since).total_seconds() < rule.for_duration:
            return None
        
        # Create alert
        alert = self._create_alert(rule, value)
        cache.delete(cache_key)
        
        return alert
    
    def _create_alert(self, rule: AlertRule, value: float) -> Optional[Alert]:
        """Create new alert"""
        # Generate fingerprint for deduplication
        fingerprint = self._generate_fingerprint(rule, value)
        
        # Check for existing active alert
        existing = Alert.objects.filter(
            fingerprint=fingerprint,
            status__in=[AlertStatus.FIRING.value, AlertStatus.PENDING.value]
        ).first()
        
        if existing:
            # Update existing alert
            existing.value = value
            existing.last_notification_at = timezone.now()
            existing.save()
            return None
        
        # Check cooldown period
        recent_alert = Alert.objects.filter(
            rule=rule,
            fired_at__gte=timezone.now() - timedelta(seconds=rule.cooldown_period)
        ).exists()
        
        if recent_alert:
            return None
        
        # Check daily limit
        today_count = Alert.objects.filter(
            rule=rule,
            fired_at__date=timezone.now().date()
        ).count()
        
        if today_count >= rule.max_alerts_per_day:
            logger.warning(f"Daily alert limit reached for rule {rule.name}")
            return None
        
        # Create alert
        alert = Alert.objects.create(
            rule=rule,
            severity=rule.severity,
            status=AlertStatus.PENDING.value,
            value=value,
            message=self._format_message(rule, value),
            labels=rule.labels,
            annotations=rule.annotations,
            fingerprint=fingerprint
        )
        
        logger.info(f"Created alert {alert.id} for rule {rule.name}")
        return alert
    
    def _resolve_alerts(self, rule: AlertRule) -> None:
        """Resolve active alerts for rule"""
        alerts = Alert.objects.filter(
            rule=rule,
            status__in=[AlertStatus.FIRING.value, AlertStatus.PENDING.value]
        )
        
        for alert in alerts:
            alert.resolve()
            logger.info(f"Resolved alert {alert.id} for rule {rule.name}")
    
    def _generate_fingerprint(self, rule: AlertRule, value: float) -> str:
        """Generate unique fingerprint for alert deduplication"""
        data = f"{rule.id}:{rule.metric_name}:{rule.labels}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _format_message(self, rule: AlertRule, value: float) -> str:
        """Format alert message"""
        return (
            f"{rule.description or rule.name}: "
            f"Current value {value:.2f} {rule.condition} threshold {rule.threshold:.2f}"
        )


class AlertManager:
    """Manage alert lifecycle and notifications"""
    
    def __init__(self):
        self.processor = AlertProcessor()
    
    def process_alerts(self) -> None:
        """Main alert processing loop"""
        # Evaluate rules
        new_alerts = self.processor.evaluate_rules()
        
        # Process new alerts
        for alert in new_alerts:
            self._process_alert(alert)
        
        # Process pending alerts
        pending_alerts = Alert.objects.filter(
            status=AlertStatus.PENDING.value
        )
        
        for alert in pending_alerts:
            self._process_alert(alert)
    
    @transaction.atomic
    def _process_alert(self, alert: Alert) -> None:
        """Process single alert"""
        try:
            # Check for silences
            if self._is_silenced(alert):
                alert.silence(0)  # Silence indefinitely
                return
            
            # Update status
            if alert.status == AlertStatus.PENDING.value:
                alert.status = AlertStatus.FIRING.value
                alert.save()
            
            # Send notifications
            self._send_notifications(alert)
            
        except Exception as e:
            logger.error(f"Error processing alert {alert.id}: {e}")
    
    def _is_silenced(self, alert: Alert) -> bool:
        """Check if alert is silenced"""
        silences = AlertSilence.objects.filter(
            active=True,
            starts_at__lte=timezone.now(),
            ends_at__gte=timezone.now()
        )
        
        for silence in silences:
            if silence.matches(alert):
                return True
        
        return False
    
    def _send_notifications(self, alert: Alert) -> None:
        """Send notifications for alert"""
        # Get applicable channels
        channels = AlertChannel.objects.filter(enabled=True)
        
        for channel in channels:
            if not channel.should_route(alert):
                continue
            
            # Check if already notified
            if channel.name in alert.notified_channels:
                continue
            
            # Check rate limit
            if self._is_rate_limited(channel):
                logger.warning(f"Channel {channel.name} is rate limited")
                continue
            
            # Send notification
            if self._send_to_channel(alert, channel):
                alert.notified_channels.append(channel.name)
                alert.notification_count += 1
                alert.last_notification_at = timezone.now()
                alert.save()
    
    def _is_rate_limited(self, channel: AlertChannel) -> bool:
        """Check if channel is rate limited"""
        cache_key = f"channel_rate_{channel.id}"
        current_count = cache.get(cache_key, 0)
        
        if current_count >= channel.rate_limit:
            return True
        
        # Increment counter
        cache.set(cache_key, current_count + 1, 3600)  # 1 hour window
        return False
    
    def _send_to_channel(self, alert: Alert, channel: AlertChannel) -> bool:
        """Send alert to specific channel"""
        channel_class = get_channel_class(channel.type)
        if not channel_class:
            logger.error(f"Unknown channel type: {channel.type}")
            return False
        
        try:
            notifier = channel_class(channel)
            return notifier.send(alert)
        except Exception as e:
            logger.error(f"Failed to send to channel {channel.name}: {e}")
            return False
    
    def acknowledge_alert(self, alert_id: int, user) -> bool:
        """Acknowledge an alert"""
        try:
            alert = Alert.objects.get(id=alert_id)
            alert.acknowledge(user)
            logger.info(f"Alert {alert_id} acknowledged by {user}")
            return True
        except Alert.DoesNotExist:
            logger.error(f"Alert {alert_id} not found")
            return False
    
    def resolve_alert(self, alert_id: int) -> bool:
        """Manually resolve an alert"""
        try:
            alert = Alert.objects.get(id=alert_id)
            alert.resolve()
            logger.info(f"Alert {alert_id} resolved")
            return True
        except Alert.DoesNotExist:
            logger.error(f"Alert {alert_id} not found")
            return False
    
    def create_silence(self, user, name: str, matchers: Dict[str, Any],
                      duration_hours: int = 4) -> AlertSilence:
        """Create alert silence"""
        starts_at = timezone.now()
        ends_at = starts_at + timedelta(hours=duration_hours)
        
        silence = AlertSilence.objects.create(
            name=name,
            matchers=matchers,
            starts_at=starts_at,
            ends_at=ends_at,
            created_by=user
        )
        
        logger.info(f"Created silence {silence.id} by {user}")
        return silence
    
    def get_alert_stats(self) -> Dict[str, Any]:
        """Get alert statistics"""
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        
        return {
            'active': Alert.objects.filter(
                status=AlertStatus.FIRING.value
            ).count(),
            'last_24h': Alert.objects.filter(
                fired_at__gte=last_24h
            ).count(),
            'last_7d': Alert.objects.filter(
                fired_at__gte=last_7d
            ).count(),
            'by_severity': {
                severity: Alert.objects.filter(
                    severity=severity,
                    fired_at__gte=last_24h
                ).count()
                for severity in ['info', 'warning', 'error', 'critical']
            },
            'top_rules': list(
                Alert.objects.filter(fired_at__gte=last_7d)
                .values('rule__name')
                .annotate(count=models.Count('id'))
                .order_by('-count')[:5]
            )
        }