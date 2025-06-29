"""
Tests for the unified email service.
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime
from django.test import TestCase, override_settings
from django.core.cache import cache

from ..services.email import EmailService, EmailTemplate
from ..providers.email.base import EmailMessage, SendResult, BulkSendResult, EmailStatus
from ..exceptions import AllProvidersFailedError


class TestEmailService(TestCase):
    """Test unified email service."""
    
    def setUp(self):
        """Set up test email service."""
        self.email_service = EmailService()
        
        # Clear cache
        cache.clear()
    
    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
    
    @patch('integrations.services.email.provider_registry')
    async def test_send_email_success(self, mock_registry):
        """Test successful email sending."""
        # Mock provider registry
        mock_result = SendResult(
            success=True,
            message_id='test-message-id',
            provider='sendgrid'
        )
        mock_registry.execute.return_value = mock_result
        
        # Send email
        result = await self.email_service.send_email(
            to='recipient@example.com',
            subject='Test Subject',
            html_content='<h1>Test Content</h1>',
            text_content='Test Content'
        )
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.message_id, 'test-message-id')
        self.assertEqual(result.provider, 'sendgrid')
        
        # Verify provider registry was called
        mock_registry.execute.assert_called_once()
        call_args = mock_registry.execute.call_args
        self.assertEqual(call_args[1]['service'], 'email')
        self.assertEqual(call_args[1]['operation'], 'send')
    
    @patch('integrations.services.email.provider_registry')
    async def test_send_email_all_providers_failed(self, mock_registry):
        """Test email sending when all providers fail."""
        # Mock provider registry failure
        mock_registry.execute.side_effect = AllProvidersFailedError("All providers failed")
        
        # Send email
        result = await self.email_service.send_email(
            to='recipient@example.com',
            subject='Test Subject',
            html_content='<h1>Test Content</h1>'
        )
        
        # Verify failure result
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'ALL_PROVIDERS_FAILED')
        self.assertIsNone(result.provider)
    
    @patch('integrations.services.email.provider_registry')
    async def test_send_email_with_template(self, mock_registry):
        """Test email sending with template."""
        # Mock provider registry
        mock_result = SendResult(
            success=True,
            message_id='test-message-id',
            provider='sendgrid'
        )
        mock_registry.execute.return_value = mock_result
        
        # Mock template loading
        test_template = EmailTemplate(
            subject='Welcome {{name}}!',
            html_content='<h1>Welcome {{name}}!</h1>',
            text_content='Welcome {{name}}!',
            from_email='welcome@example.com',
            from_name='Welcome Team'
        )
        
        with patch.object(self.email_service, '_get_template', return_value=test_template):
            # Send email with template
            result = await self.email_service.send_email(
                to='recipient@example.com',
                template_id='welcome',
                template_data={'name': 'John Doe'}
            )
        
        # Verify result
        self.assertTrue(result.success)
        
        # Verify template was rendered
        call_args = mock_registry.execute.call_args
        message = call_args[1]['message']
        self.assertEqual(message.subject, 'Welcome John Doe!')
        self.assertIn('Welcome John Doe!', message.html_content)
        self.assertEqual(message.from_email, 'welcome@example.com')
        self.assertEqual(message.from_name, 'Welcome Team')
    
    @patch('integrations.services.email.provider_registry')
    async def test_send_email_with_force_provider(self, mock_registry):
        """Test email sending with forced provider."""
        # Mock specific provider
        mock_provider = Mock()
        mock_provider.send.return_value = SendResult(
            success=True,
            message_id='test-message-id',
            provider='mailgun'
        )
        mock_registry.get_provider.return_value = mock_provider
        
        # Send email with forced provider
        result = await self.email_service.send_email(
            to='recipient@example.com',
            subject='Test Subject',
            html_content='<h1>Test Content</h1>',
            force_provider='mailgun'
        )
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.provider, 'mailgun')
        
        # Verify specific provider was used
        mock_registry.get_provider.assert_called_once_with('email', 'mailgun')
        mock_provider.send.assert_called_once()
    
    @patch('integrations.services.email.provider_registry')
    async def test_send_bulk_emails(self, mock_registry):
        """Test bulk email sending."""
        # Mock provider registry
        mock_result = BulkSendResult(
            total=2,
            successful=2,
            failed=0,
            results=[
                SendResult(success=True, message_id='msg-1', provider='sendgrid'),
                SendResult(success=True, message_id='msg-2', provider='sendgrid')
            ],
            provider='sendgrid'
        )
        mock_registry.execute.return_value = mock_result
        
        # Send bulk emails
        messages = [
            {
                'to': 'user1@example.com',
                'subject': 'Test 1',
                'html_content': '<h1>Test 1</h1>'
            },
            {
                'to': 'user2@example.com',
                'subject': 'Test 2',
                'html_content': '<h1>Test 2</h1>'
            }
        ]
        
        result = await self.email_service.send_bulk(messages)
        
        # Verify result
        self.assertEqual(result.total, 2)
        self.assertEqual(result.successful, 2)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.provider, 'sendgrid')
        
        # Verify provider registry was called
        mock_registry.execute.assert_called_once()
        call_args = mock_registry.execute.call_args
        self.assertEqual(call_args[1]['service'], 'email')
        self.assertEqual(call_args[1]['operation'], 'send_bulk')
    
    @override_settings(
        APP_NAME='TestApp',
        FRONTEND_URL='https://test.example.com',
        SUPPORT_EMAIL='support@test.example.com'
    )
    @patch('integrations.services.email.provider_registry')
    async def test_send_transactional_email(self, mock_registry):
        """Test transactional email sending."""
        # Mock provider registry
        mock_result = SendResult(
            success=True,
            message_id='test-message-id',
            provider='sendgrid'
        )
        mock_registry.execute.return_value = mock_result
        
        # Mock template loading
        test_template = EmailTemplate(
            subject='Password Reset - {{app_name}}',
            html_content='<h1>Reset your password for {{app_name}}</h1><p>Click <a href="{{reset_url}}">here</a></p>',
            text_content='Reset your password for {{app_name}}: {{reset_url}}'
        )
        
        with patch.object(self.email_service, '_get_template', return_value=test_template):
            # Send transactional email
            result = await self.email_service.send_transactional(
                to='user@example.com',
                template_slug='password-reset',
                context={'reset_url': 'https://test.example.com/reset/abc123'}
            )
        
        # Verify result
        self.assertTrue(result.success)
        
        # Verify system context was added
        call_args = mock_registry.execute.call_args
        message = call_args[1]['message']
        self.assertIn('TestApp', message.subject)
        self.assertIn('TestApp', message.html_content)
        self.assertIn('transactional', message.tags)
        self.assertIn('password-reset', message.tags)
    
    @patch('integrations.services.email.provider_registry')
    async def test_process_webhook(self, mock_registry):
        """Test webhook processing."""
        # Mock provider
        mock_provider = Mock()
        mock_events = [
            Mock(
                message_id='test-message-id',
                event_type=EmailStatus.DELIVERED,
                recipient='test@example.com'
            )
        ]
        mock_provider.process_webhook.return_value = mock_events
        mock_registry.get_provider.return_value = mock_provider
        
        # Process webhook
        with patch.object(self.email_service, '_track_email_event') as mock_track:
            events = await self.email_service.process_webhook(
                provider_name='sendgrid',
                data={'event': 'delivered', 'email': 'test@example.com'}
            )
        
        # Verify events
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EmailStatus.DELIVERED)
        
        # Verify tracking was called
        mock_track.assert_called_once()
    
    @patch('integrations.services.email.provider_registry')
    async def test_get_provider_health(self, mock_registry):
        """Test provider health status."""
        # Mock provider registry methods
        mock_registry.get_available_providers.return_value = ['sendgrid', 'mailgun']
        
        # Mock providers
        mock_sendgrid = Mock()
        mock_sendgrid.health_check.return_value = True
        
        mock_mailgun = Mock()
        mock_mailgun.health_check.return_value = False
        
        def mock_get_provider(service, provider):
            if provider == 'sendgrid':
                return mock_sendgrid
            elif provider == 'mailgun':
                return mock_mailgun
        
        mock_registry.get_provider.side_effect = mock_get_provider
        mock_registry.get_circuit_breaker_states.return_value = {
            'email.sendgrid': {'state': 'closed', 'failure_count': 0},
            'email.mailgun': {'state': 'open', 'failure_count': 5}
        }
        mock_registry.get_provider_metrics.return_value = {
            'email': {
                'sendgrid': {'request_count': 100, 'error_count': 2},
                'mailgun': {'request_count': 50, 'error_count': 10}
            }
        }
        
        # Get health status
        health = await self.email_service.get_provider_health()
        
        # Verify health status
        self.assertIn('sendgrid', health)
        self.assertIn('mailgun', health)
        
        # Check SendGrid status
        sendgrid_health = health['sendgrid']
        self.assertTrue(sendgrid_health['healthy'])
        self.assertEqual(sendgrid_health['circuit_breaker']['state'], 'closed')
        self.assertEqual(sendgrid_health['metrics']['request_count'], 100)
        
        # Check Mailgun status
        mailgun_health = health['mailgun']
        self.assertFalse(mailgun_health['healthy'])
        self.assertEqual(mailgun_health['circuit_breaker']['state'], 'open')
        self.assertEqual(mailgun_health['metrics']['error_count'], 10)
    
    @patch('contacts.models.EmailTemplate.objects')
    async def test_get_template_from_database(self, mock_template_objects):
        """Test template loading from database."""
        # Mock database template
        mock_db_template = Mock()
        mock_db_template.subject = 'Test Subject'
        mock_db_template.html_content = '<h1>Test HTML</h1>'
        mock_db_template.text_content = 'Test Text'
        mock_db_template.from_email = 'test@example.com'
        mock_db_template.from_name = 'Test Sender'
        mock_db_template.reply_to_email = 'reply@example.com'
        
        # Mock async database query
        mock_template_objects.get = AsyncMock(return_value=mock_db_template)
        
        # Get template
        template = await self.email_service._get_template('test-template')
        
        # Verify template
        self.assertEqual(template.subject, 'Test Subject')
        self.assertEqual(template.html_content, '<h1>Test HTML</h1>')
        self.assertEqual(template.text_content, 'Test Text')
        self.assertEqual(template.from_email, 'test@example.com')
        self.assertEqual(template.from_name, 'Test Sender')
        self.assertEqual(template.reply_to, 'reply@example.com')
        
        # Verify database was queried
        mock_template_objects.get.assert_called_once_with(
            slug='test-template',
            is_active=True
        )
    
    @patch('contacts.models.EmailTemplate.objects')
    async def test_get_template_not_found(self, mock_template_objects):
        """Test template not found error."""
        from contacts.models import EmailTemplate as DbEmailTemplate
        
        # Mock database template not found
        mock_template_objects.get = AsyncMock(
            side_effect=DbEmailTemplate.DoesNotExist()
        )
        
        # Test template not found
        with self.assertRaises(ValueError) as context:
            await self.email_service._get_template('nonexistent-template')
        
        self.assertIn('not found', str(context.exception))
    
    async def test_render_template_jinja2(self):
        """Test template rendering with Jinja2."""
        template_str = '<h1>Hello {{name}}!</h1><p>Welcome to {{app_name}}</p>'
        context = {
            'name': 'John Doe',
            'app_name': 'TestApp'
        }
        
        # Render template
        result = await self.email_service._render_template(template_str, context)
        
        # Verify rendered content
        self.assertEqual(result, '<h1>Hello John Doe!</h1><p>Welcome to TestApp</p>')
    
    async def test_render_template_with_filters(self):
        """Test template rendering with custom filters."""
        template_str = '<h1>Hello {{name|title}}!</h1><p>{{message|default("No message")}}</p>'
        context = {
            'name': 'john doe',
            'message': None
        }
        
        # Render template
        result = await self.email_service._render_template(template_str, context)
        
        # Verify rendered content with filters
        self.assertEqual(result, '<h1>Hello John Doe!</h1><p>No message</p>')
    
    @patch('integrations.services.email.transform')
    async def test_process_html_css_inlining(self, mock_transform):
        """Test HTML processing with CSS inlining."""
        html_content = '<style>h1{color:red}</style><h1>Test</h1>'
        processed_html = '<h1 style="color:red">Test</h1>'
        
        # Mock premailer transform
        mock_transform.return_value = processed_html
        
        # Process HTML
        result = await self.email_service._process_html(html_content)
        
        # Verify CSS was inlined
        self.assertEqual(result, processed_html)
        mock_transform.assert_called_once()
    
    @patch('integrations.services.email.transform')
    async def test_process_html_fallback_on_error(self, mock_transform):
        """Test HTML processing fallback when CSS inlining fails."""
        html_content = '<h1>Test</h1>'
        
        # Mock premailer error
        mock_transform.side_effect = Exception('CSS processing failed')
        
        # Process HTML
        result = await self.email_service._process_html(html_content)
        
        # Verify original HTML is returned
        self.assertEqual(result, html_content)
    
    def test_email_service_singleton_pattern(self):
        """Test that email service follows singleton pattern."""
        from integrations.services.email import email_service
        
        # Import should return the same instance
        service1 = email_service
        service2 = email_service
        
        self.assertIs(service1, service2)
    
    async def test_send_email_to_multiple_recipients(self):
        """Test sending email to multiple recipients."""
        with patch('integrations.services.email.provider_registry') as mock_registry:
            mock_result = SendResult(
                success=True,
                message_id='test-message-id',
                provider='sendgrid'
            )
            mock_registry.execute.return_value = mock_result
            
            # Send to multiple recipients
            result = await self.email_service.send_email(
                to=['user1@example.com', 'user2@example.com'],
                subject='Test Subject',
                html_content='<h1>Test Content</h1>'
            )
            
            # Verify result
            self.assertTrue(result.success)
            
            # Verify message has multiple recipients
            call_args = mock_registry.execute.call_args
            message = call_args[1]['message']
            self.assertEqual(len(message.to), 2)
            self.assertIn('user1@example.com', message.to)
            self.assertIn('user2@example.com', message.to)