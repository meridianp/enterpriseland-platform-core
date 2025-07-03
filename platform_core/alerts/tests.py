"""
Alert System Tests
"""
import json
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status

from .models import Alert, AlertRule, AlertChannel, AlertStatus, AlertSilence
from .services import AlertManager, AlertProcessor
from .channels import EmailChannel, SlackChannel, WebhookChannel

User = get_user_model()


class AlertRuleModelTest(TestCase):
    """Test AlertRule model"""
    
    def setUp(self):
        self.rule = AlertRule.objects.create(
            name='Test Rule',
            description='Test description',
            metric_name='test_metric',
            condition='>',
            threshold=10.0,
            severity='warning'
        )
    
    def test_rule_creation(self):
        """Test rule is created correctly"""
        self.assertEqual(self.rule.name, 'Test Rule')
        self.assertEqual(self.rule.metric_name, 'test_metric')
        self.assertEqual(self.rule.threshold, 10.0)
    
    def test_evaluate_greater_than(self):
        """Test evaluation with greater than condition"""
        self.assertTrue(self.rule.evaluate(15.0))
        self.assertFalse(self.rule.evaluate(5.0))
        self.assertFalse(self.rule.evaluate(10.0))
    
    def test_evaluate_all_conditions(self):
        """Test all condition types"""
        # Test each condition
        conditions = [
            ('>', 10.0, 15.0, True),
            ('>', 10.0, 5.0, False),
            ('>=', 10.0, 10.0, True),
            ('>=', 10.0, 5.0, False),
            ('<', 10.0, 5.0, True),
            ('<', 10.0, 15.0, False),
            ('<=', 10.0, 10.0, True),
            ('<=', 10.0, 15.0, False),
            ('==', 10.0, 10.0, True),
            ('==', 10.0, 15.0, False),
            ('!=', 10.0, 15.0, True),
            ('!=', 10.0, 10.0, False),
        ]
        
        for condition, threshold, value, expected in conditions:
            self.rule.condition = condition
            self.rule.threshold = threshold
            self.assertEqual(
                self.rule.evaluate(value),
                expected,
                f"Failed: {value} {condition} {threshold}"
            )


class AlertChannelModelTest(TestCase):
    """Test AlertChannel model"""
    
    def setUp(self):
        self.channel = AlertChannel.objects.create(
            name='Test Email Channel',
            type='email',
            configuration={'recipients': ['test@example.com']},
            severities=['warning', 'error'],
            labels={'team': 'backend'}
        )
    
    def test_channel_creation(self):
        """Test channel is created correctly"""
        self.assertEqual(self.channel.name, 'Test Email Channel')
        self.assertEqual(self.channel.type, 'email')
        self.assertIn('test@example.com', self.channel.configuration['recipients'])
    
    def test_should_route_severity(self):
        """Test routing based on severity"""
        rule = AlertRule.objects.create(
            name='Test Rule',
            metric_name='test_metric',
            condition='>',
            threshold=10.0,
            severity='warning'
        )
        
        alert_warning = Alert(
            rule=rule,
            severity='warning',
            status='firing',
            value=15.0,
            message='Test',
            labels={'team': 'backend'},
            fingerprint='test1'
        )
        
        alert_info = Alert(
            rule=rule,
            severity='info',
            status='firing',
            value=15.0,
            message='Test',
            labels={'team': 'backend'},
            fingerprint='test2'
        )
        
        self.assertTrue(self.channel.should_route(alert_warning))
        self.assertFalse(self.channel.should_route(alert_info))
    
    def test_should_route_labels(self):
        """Test routing based on labels"""
        rule = AlertRule.objects.create(
            name='Test Rule',
            metric_name='test_metric',
            condition='>',
            threshold=10.0,
            severity='warning'
        )
        
        alert_backend = Alert(
            rule=rule,
            severity='warning',
            status='firing',
            value=15.0,
            message='Test',
            labels={'team': 'backend'},
            fingerprint='test1'
        )
        
        alert_frontend = Alert(
            rule=rule,
            severity='warning',
            status='firing',
            value=15.0,
            message='Test',
            labels={'team': 'frontend'},
            fingerprint='test2'
        )
        
        self.assertTrue(self.channel.should_route(alert_backend))
        self.assertFalse(self.channel.should_route(alert_frontend))


class AlertProcessorTest(TestCase):
    """Test AlertProcessor"""
    
    def setUp(self):
        self.processor = AlertProcessor()
        self.rule = AlertRule.objects.create(
            name='Test Rule',
            metric_name='test_metric',
            condition='>',
            threshold=10.0,
            severity='warning',
            for_duration=0  # No duration for testing
        )
    
    @patch('platform_core.alerts.services.MetricsRegistry')
    def test_evaluate_rules_creates_alert(self, mock_registry):
        """Test that evaluating rules creates alerts when conditions are met"""
        # Mock metric value
        mock_metric = MagicMock()
        mock_metric.value = 15.0
        mock_registry.return_value.get_metric.return_value = mock_metric
        
        # Evaluate rules
        alerts = self.processor.evaluate_rules()
        
        # Check alert was created
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.rule, self.rule)
        self.assertEqual(alert.value, 15.0)
        self.assertEqual(alert.status, AlertStatus.PENDING.value)
    
    @patch('platform_core.alerts.services.MetricsRegistry')
    def test_evaluate_rules_resolves_alert(self, mock_registry):
        """Test that alerts are resolved when condition is no longer met"""
        # Create existing alert
        alert = Alert.objects.create(
            rule=self.rule,
            severity='warning',
            status=AlertStatus.FIRING.value,
            value=15.0,
            message='Test alert',
            fingerprint='test123'
        )
        
        # Mock metric value below threshold
        mock_metric = MagicMock()
        mock_metric.value = 5.0
        mock_registry.return_value.get_metric.return_value = mock_metric
        
        # Evaluate rules
        alerts = self.processor.evaluate_rules()
        
        # Check alert was resolved
        alert.refresh_from_db()
        self.assertEqual(alert.status, AlertStatus.RESOLVED.value)
        self.assertEqual(len(alerts), 0)


class AlertManagerTest(TransactionTestCase):
    """Test AlertManager"""
    
    def setUp(self):
        self.manager = AlertManager()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.rule = AlertRule.objects.create(
            name='Test Rule',
            metric_name='test_metric',
            condition='>',
            threshold=10.0,
            severity='warning'
        )
        self.channel = AlertChannel.objects.create(
            name='Test Channel',
            type='email',
            configuration={'recipients': ['test@example.com']},
            severities=['warning'],
            enabled=True
        )
    
    @patch('platform_core.alerts.channels.send_mail')
    def test_send_notifications(self, mock_send_mail):
        """Test sending notifications"""
        alert = Alert.objects.create(
            rule=self.rule,
            severity='warning',
            status=AlertStatus.FIRING.value,
            value=15.0,
            message='Test alert',
            fingerprint='test123'
        )
        
        self.manager._send_notifications(alert)
        
        # Check notification was sent
        mock_send_mail.assert_called_once()
        alert.refresh_from_db()
        self.assertIn(self.channel.name, alert.notified_channels)
    
    def test_acknowledge_alert(self):
        """Test acknowledging an alert"""
        alert = Alert.objects.create(
            rule=self.rule,
            severity='warning',
            status=AlertStatus.FIRING.value,
            value=15.0,
            message='Test alert',
            fingerprint='test123'
        )
        
        success = self.manager.acknowledge_alert(alert.id, self.user)
        
        self.assertTrue(success)
        alert.refresh_from_db()
        self.assertEqual(alert.status, AlertStatus.ACKNOWLEDGED.value)
        self.assertEqual(alert.acknowledged_by, self.user)
    
    def test_create_silence(self):
        """Test creating an alert silence"""
        silence = self.manager.create_silence(
            self.user,
            'Test Silence',
            {'team': 'backend'},
            duration_hours=2
        )
        
        self.assertEqual(silence.name, 'Test Silence')
        self.assertEqual(silence.created_by, self.user)
        self.assertTrue(silence.active)
        
        # Check duration
        duration = silence.ends_at - silence.starts_at
        self.assertEqual(duration.total_seconds(), 7200)  # 2 hours


class AlertChannelTest(TestCase):
    """Test alert notification channels"""
    
    def setUp(self):
        self.rule = AlertRule.objects.create(
            name='Test Rule',
            metric_name='test_metric',
            condition='>',
            threshold=10.0,
            severity='warning'
        )
        self.alert = Alert(
            rule=self.rule,
            severity='warning',
            status=AlertStatus.FIRING.value,
            value=15.0,
            message='Test alert message',
            labels={'team': 'backend'},
            annotations={'runbook': 'http://example.com/runbook'},
            fired_at=timezone.now(),
            fingerprint='test123'
        )
    
    @patch('platform_core.alerts.channels.send_mail')
    def test_email_channel(self, mock_send_mail):
        """Test email notification channel"""
        channel = AlertChannel.objects.create(
            name='Email Channel',
            type='email',
            configuration={'recipients': ['test@example.com', 'test2@example.com']}
        )
        
        email_channel = EmailChannel(channel)
        success = email_channel.send(self.alert)
        
        self.assertTrue(success)
        mock_send_mail.assert_called_once()
        
        # Check email details
        call_args = mock_send_mail.call_args
        self.assertIn('[WARNING] Test Rule', call_args.kwargs['subject'])
        self.assertEqual(call_args.kwargs['recipient_list'], ['test@example.com', 'test2@example.com'])
    
    @patch('requests.post')
    def test_slack_channel(self, mock_post):
        """Test Slack notification channel"""
        mock_post.return_value.status_code = 200
        
        channel = AlertChannel.objects.create(
            name='Slack Channel',
            type='slack',
            configuration={
                'webhook_url': 'https://hooks.slack.com/test',
                'channel': '#alerts'
            }
        )
        
        slack_channel = SlackChannel(channel)
        success = slack_channel.send(self.alert)
        
        self.assertTrue(success)
        mock_post.assert_called_once()
        
        # Check Slack payload
        call_args = mock_post.call_args
        payload = call_args.kwargs['json']
        self.assertEqual(payload['channel'], '#alerts')
        self.assertEqual(len(payload['attachments']), 1)
        self.assertEqual(payload['attachments'][0]['color'], '#ff9800')  # Warning color
    
    @patch('requests.post')
    def test_webhook_channel(self, mock_post):
        """Test webhook notification channel"""
        mock_post.return_value.status_code = 200
        
        channel = AlertChannel.objects.create(
            name='Webhook Channel',
            type='webhook',
            configuration={
                'url': 'https://example.com/webhook',
                'headers': {'X-Custom': 'value'},
                'auth_type': 'bearer',
                'token': 'test-token'
            }
        )
        
        webhook_channel = WebhookChannel(channel)
        self.alert.save()  # Save to get ID
        success = webhook_channel.send(self.alert)
        
        self.assertTrue(success)
        mock_post.assert_called_once()
        
        # Check webhook details
        call_args = mock_post.call_args
        self.assertEqual(call_args.args[0], 'https://example.com/webhook')
        self.assertEqual(call_args.kwargs['headers']['Authorization'], 'Bearer test-token')
        self.assertEqual(call_args.kwargs['headers']['X-Custom'], 'value')


class AlertAPITest(APITestCase):
    """Test Alert API endpoints"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.client.force_authenticate(user=self.user)
        
        self.rule = AlertRule.objects.create(
            name='Test Rule',
            metric_name='test_metric',
            condition='>',
            threshold=10.0,
            severity='warning'
        )
    
    def test_list_alert_rules(self):
        """Test listing alert rules"""
        response = self.client.get('/api/alerts/rules/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_create_alert_rule(self):
        """Test creating an alert rule"""
        data = {
            'name': 'New Rule',
            'description': 'New rule description',
            'metric_name': 'new_metric',
            'condition': '<',
            'threshold': 5.0,
            'severity': 'error',
            'evaluation_interval': 60,
            'for_duration': 300
        }
        
        response = self.client.post('/api/alerts/rules/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(AlertRule.objects.count(), 2)
    
    def test_test_alert_rule(self):
        """Test the test endpoint for alert rules"""
        response = self.client.post(
            f'/api/alerts/rules/{self.rule.id}/test/',
            {'rule_id': self.rule.id, 'value': 15.0},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Alert.objects.count(), 1)
        
        alert = Alert.objects.first()
        self.assertEqual(alert.value, 15.0)
        self.assertTrue(alert.labels.get('test'))
    
    def test_acknowledge_alerts(self):
        """Test acknowledging alerts"""
        alert1 = Alert.objects.create(
            rule=self.rule,
            severity='warning',
            status=AlertStatus.FIRING.value,
            value=15.0,
            message='Test alert 1',
            fingerprint='test1'
        )
        alert2 = Alert.objects.create(
            rule=self.rule,
            severity='warning',
            status=AlertStatus.FIRING.value,
            value=20.0,
            message='Test alert 2',
            fingerprint='test2'
        )
        
        response = self.client.post(
            '/api/alerts/alerts/acknowledge/',
            {'alert_ids': [alert1.id, alert2.id]},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        
        alert1.refresh_from_db()
        alert2.refresh_from_db()
        self.assertEqual(alert1.status, AlertStatus.ACKNOWLEDGED.value)
        self.assertEqual(alert2.status, AlertStatus.ACKNOWLEDGED.value)
    
    def test_create_silence(self):
        """Test creating an alert silence"""
        data = {
            'name': 'Maintenance Window',
            'description': 'Silencing alerts during maintenance',
            'matchers': {'team': 'backend'},
            'duration_hours': 4
        }
        
        response = self.client.post('/api/alerts/silences/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        silence = AlertSilence.objects.first()
        self.assertEqual(silence.name, 'Maintenance Window')
        self.assertEqual(silence.created_by, self.user)
        
        # Check duration
        duration = silence.ends_at - silence.starts_at
        self.assertEqual(duration.total_seconds(), 14400)  # 4 hours
    
    def test_get_alert_stats(self):
        """Test getting alert statistics"""
        # Create some alerts
        for i in range(5):
            Alert.objects.create(
                rule=self.rule,
                severity='warning' if i < 3 else 'error',
                status=AlertStatus.FIRING.value if i < 2 else AlertStatus.RESOLVED.value,
                value=15.0 + i,
                message=f'Test alert {i}',
                fingerprint=f'test{i}',
                fired_at=timezone.now() - timedelta(hours=i)
            )
        
        response = self.client.get('/api/alerts/alerts/stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        stats = response.data
        self.assertEqual(stats['active'], 2)
        self.assertGreaterEqual(stats['last_24h'], 5)
        self.assertEqual(stats['by_severity']['warning'], 3)
        self.assertEqual(stats['by_severity']['error'], 2)