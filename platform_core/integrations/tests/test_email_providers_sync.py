"""
Tests for email provider implementations (sync version).
"""
import asyncio
from unittest.mock import Mock, patch
from datetime import datetime
from django.test import TestCase

from ..providers.email.sendgrid import SendGridProvider
from ..providers.email.aws_ses import AWSSESProvider
from ..providers.email.mailgun import MailgunProvider
from ..providers.email.base import EmailMessage, SendResult, EmailStatus, EmailEvent
from ..providers.base import ProviderConfig


def run_async_test(coro):
    """Helper to run async tests in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSendGridProvider(TestCase):
    """Test SendGrid email provider."""
    
    def setUp(self):
        """Set up test SendGrid provider."""
        config = ProviderConfig(
            name="sendgrid",
            enabled=True,
            params={
                'api_key': 'test_api_key',
                'from_email': 'test@example.com',
                'from_name': 'Test Sender',
                'sandbox_mode': True
            }
        )
        self.provider = SendGridProvider(config)
    
    def test_initialization(self):
        """Test provider initialization."""
        self.assertEqual(self.provider.api_key, 'test_api_key')
        self.assertEqual(self.provider.from_email, 'test@example.com')
        self.assertEqual(self.provider.from_name, 'Test Sender')
        self.assertTrue(self.provider.sandbox_mode)
    
    @patch('integrations.providers.email.sendgrid.SendGridAPIClient')
    def test_send_email_success(self, mock_client):
        """Test successful email sending."""
        # Mock SendGrid response
        mock_response = Mock()
        mock_response.status_code = 202
        mock_response.headers = {'X-Message-Id': 'test-message-id'}
        
        # Re-initialize provider with mock client
        config = ProviderConfig(
            name="sendgrid",
            enabled=True,
            params={
                'api_key': 'test_api_key',
                'from_email': 'test@example.com',
                'from_name': 'Test Sender',
                'sandbox_mode': True
            }
        )
        provider = SendGridProvider(config)
        
        mock_sg_client = Mock()
        mock_sg_client.send.return_value = mock_response
        provider.client = mock_sg_client
        
        # Create test message
        message = EmailMessage(
            to=['recipient@example.com'],
            subject='Test Subject',
            html_content='<h1>Test Content</h1>',
            text_content='Test Content'
        )
        
        # Send email
        result = run_async_test(provider.send(message))
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.message_id, 'test-message-id')
        self.assertEqual(result.provider, 'sendgrid')
        
        # Verify SendGrid client was called
        mock_sg_client.send.assert_called_once()
    
    @patch('integrations.providers.email.sendgrid.SendGridAPIClient')
    def test_send_email_failure(self, mock_client):
        """Test email sending failure."""
        from python_http_client.exceptions import HTTPError
        
        # Re-initialize provider with mock client
        config = ProviderConfig(
            name="sendgrid",
            enabled=True,
            params={
                'api_key': 'test_api_key',
                'from_email': 'test@example.com',
                'from_name': 'Test Sender',
                'sandbox_mode': True
            }
        )
        provider = SendGridProvider(config)
        
        # Mock SendGrid error
        mock_sg_client = Mock()
        error = HTTPError(Mock(), Mock())
        error.status_code = 400
        error.body = 'Bad Request'
        mock_sg_client.send.side_effect = error
        provider.client = mock_sg_client
        
        # Create test message
        message = EmailMessage(
            to=['recipient@example.com'],
            subject='Test Subject',
            html_content='<h1>Test Content</h1>'
        )
        
        # Send email
        result = run_async_test(provider.send(message))
        
        # Verify failure
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, '400')
        self.assertEqual(result.provider, 'sendgrid')
    
    def test_process_webhook(self):
        """Test webhook processing."""
        webhook_data = [
            {
                'event': 'delivered',
                'email': 'test@example.com',
                'timestamp': 1640995200,
                'sg_message_id': 'test-message-id'
            },
            {
                'event': 'open',
                'email': 'test@example.com',
                'timestamp': 1640995260,
                'sg_message_id': 'test-message-id',
                'useragent': 'Mozilla/5.0...',
                'ip': '192.168.1.1'
            }
        ]
        
        # Process webhook
        events = run_async_test(self.provider.process_webhook(webhook_data))
        
        # Verify events
        self.assertEqual(len(events), 2)
        
        # Check delivered event
        delivered_event = events[0]
        self.assertEqual(delivered_event.event_type, EmailStatus.DELIVERED)
        self.assertEqual(delivered_event.recipient, 'test@example.com')
        self.assertEqual(delivered_event.provider, 'sendgrid')
        
        # Check open event
        open_event = events[1]
        self.assertEqual(open_event.event_type, EmailStatus.OPENED)
        self.assertEqual(open_event.user_agent, 'Mozilla/5.0...')
        self.assertEqual(open_event.ip_address, '192.168.1.1')
    
    def test_build_mail_object(self):
        """Test Mail object construction."""
        message = EmailMessage(
            to=['recipient@example.com'],
            subject='Test Subject',
            html_content='<h1>Test Content</h1>',
            text_content='Test Content'
        )
        
        mail = self.provider._build_mail_object(message)
        
        # Verify mail object is created without errors
        self.assertIsNotNone(mail)
        # SendGrid Mail object structure is complex and internal,
        # so we just verify it's created successfully


class TestAWSSESProvider(TestCase):
    """Test AWS SES email provider."""
    
    def setUp(self):
        """Set up test AWS SES provider."""
        config = ProviderConfig(
            name="aws_ses",
            enabled=True,
            params={
                'aws_access_key_id': 'test_access_key',
                'aws_secret_access_key': 'test_secret_key',
                'aws_region': 'us-east-1',
                'from_email': 'test@example.com'
            }
        )
        self.provider = AWSSESProvider(config)
    
    def test_initialization(self):
        """Test provider initialization."""
        self.assertEqual(self.provider.aws_access_key_id, 'test_access_key')
        self.assertEqual(self.provider.aws_secret_access_key, 'test_secret_key')
        self.assertEqual(self.provider.aws_region, 'us-east-1')
        self.assertEqual(self.provider.from_email, 'test@example.com')
    
    @patch('integrations.providers.email.aws_ses.boto3')
    def test_send_email_success(self, mock_boto3):
        """Test successful email sending."""
        # Mock SES client
        mock_client = Mock()
        mock_client.send_email.return_value = {
            'MessageId': 'test-message-id',
            'ResponseMetadata': {
                'RequestId': 'test-request-id',
                'HTTPStatusCode': 200
            }
        }
        
        # Re-initialize provider with mock client
        config = ProviderConfig(
            name="aws_ses",
            enabled=True,
            params={
                'aws_access_key_id': 'test_access_key',
                'aws_secret_access_key': 'test_secret_key',
                'aws_region': 'us-east-1',
                'from_email': 'test@example.com'
            }
        )
        provider = AWSSESProvider(config)
        provider.client = mock_client
        
        # Create test message
        message = EmailMessage(
            to=['recipient@example.com'],
            subject='Test Subject',
            html_content='<h1>Test Content</h1>',
            text_content='Test Content'
        )
        
        # Send email
        result = run_async_test(provider.send(message))
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.message_id, 'test-message-id')
        self.assertEqual(result.provider, 'aws_ses')
        
        # Verify SES client was called
        mock_client.send_email.assert_called_once()
    
    def test_process_webhook_sns(self):
        """Test SNS webhook processing."""
        sns_data = {
            'Message': '{"notificationType":"Bounce","mail":{"messageId":"test-message-id","timestamp":"2022-01-01T12:00:00.000Z","destination":["test@example.com"]},"bounce":{"bounceType":"Permanent","bounceSubType":"General","bouncedRecipients":[{"emailAddress":"test@example.com","action":"failed","status":"5.1.1","diagnosticCode":"smtp; 550 5.1.1 User unknown"}],"timestamp":"2022-01-01T12:00:05.000Z"}}'
        }
        
        # Process webhook
        events = run_async_test(self.provider.process_webhook(sns_data))
        
        # Verify events
        self.assertEqual(len(events), 1)
        
        bounce_event = events[0]
        self.assertEqual(bounce_event.event_type, EmailStatus.BOUNCED)
        self.assertEqual(bounce_event.recipient, 'test@example.com')
        self.assertEqual(bounce_event.provider, 'aws_ses')
        self.assertIn('Permanent', bounce_event.reason)
    
    def test_build_ses_message(self):
        """Test SES message construction."""
        message = EmailMessage(
            to=['recipient@example.com'],
            subject='Test Subject',
            html_content='<h1>Test Content</h1>',
            text_content='Test Content',
            cc=['cc@example.com'],
            reply_to='reply@example.com',
            tags=['test']
        )
        
        ses_message = self.provider._build_ses_message(message)
        
        # Verify SES message structure
        self.assertIn('Source', ses_message)
        self.assertIn('Destination', ses_message)
        self.assertIn('Message', ses_message)
        
        self.assertEqual(ses_message['Destination']['ToAddresses'], ['recipient@example.com'])
        self.assertEqual(ses_message['Destination']['CcAddresses'], ['cc@example.com'])
        self.assertEqual(ses_message['ReplyToAddresses'], ['reply@example.com'])
        self.assertEqual(ses_message['Message']['Subject']['Data'], 'Test Subject')


class TestMailgunProvider(TestCase):
    """Test Mailgun email provider."""
    
    def setUp(self):
        """Set up test Mailgun provider."""
        config = ProviderConfig(
            name="mailgun",
            enabled=True,
            params={
                'api_key': 'test_api_key',
                'domain': 'test.example.com',
                'from_email': 'test@example.com',
                'webhook_signing_key': 'test_signing_key'
            }
        )
        self.provider = MailgunProvider(config)
    
    def test_initialization(self):
        """Test provider initialization."""
        self.assertEqual(self.provider.api_key, 'test_api_key')
        self.assertEqual(self.provider.domain, 'test.example.com')
        self.assertEqual(self.provider.from_email, 'test@example.com')
        self.assertEqual(self.provider.webhook_signing_key, 'test_signing_key')
        self.assertEqual(self.provider.base_url, 'https://api.mailgun.net/v3')
    
    def test_process_webhook(self):
        """Test webhook processing."""
        webhook_data = {
            'event': 'delivered',
            'recipient': 'test@example.com',
            'timestamp': 1640995200,
            'message-id': 'test-message-id@test.example.com'
        }
        
        # Process webhook
        events = run_async_test(self.provider.process_webhook(webhook_data))
        
        # Verify events
        self.assertEqual(len(events), 1)
        
        event = events[0]
        self.assertEqual(event.event_type, EmailStatus.DELIVERED)
        self.assertEqual(event.recipient, 'test@example.com')
        self.assertEqual(event.message_id, 'test-message-id@test.example.com')
        self.assertEqual(event.provider, 'mailgun')
    
    def test_validate_webhook_signature(self):
        """Test webhook signature validation."""
        timestamp = '1640995200'
        token = 'test-token'
        signature = '1234567890abcdef'
        
        # Test with correct signature
        with patch('hmac.compare_digest', return_value=True):
            is_valid = run_async_test(self.provider.validate_webhook_signature(
                timestamp, token, signature
            ))
            self.assertTrue(is_valid)
        
        # Test with incorrect signature
        with patch('hmac.compare_digest', return_value=False):
            is_valid = run_async_test(self.provider.validate_webhook_signature(
                timestamp, token, 'wrong-signature'
            ))
            self.assertFalse(is_valid)
    
    def test_build_mailgun_data(self):
        """Test Mailgun data construction."""
        message = EmailMessage(
            to=['recipient@example.com'],
            subject='Test Subject',
            html_content='<h1>Test Content</h1>',
            text_content='Test Content',
            cc=['cc@example.com'],
            bcc=['bcc@example.com'],
            reply_to='reply@example.com',
            tags=['test', 'automated'],
            metadata={'campaign': 'test_campaign'},
            track_opens=True,
            track_clicks=True
        )
        
        data = self.provider._build_mailgun_data(message)
        
        # Verify data structure
        self.assertEqual(data['to'], ['recipient@example.com'])
        self.assertEqual(data['subject'], 'Test Subject')
        self.assertEqual(data['html'], '<h1>Test Content</h1>')
        self.assertEqual(data['text'], 'Test Content')
        self.assertEqual(data['cc'], ['cc@example.com'])
        self.assertEqual(data['bcc'], ['bcc@example.com'])
        self.assertEqual(data['h:Reply-To'], 'reply@example.com')
        self.assertEqual(data['o:tracking'], 'yes')
        self.assertEqual(data['o:tracking-clicks'], 'yes')
        self.assertEqual(data['o:tracking-opens'], 'yes')
        self.assertEqual(data['v:campaign'], 'test_campaign')