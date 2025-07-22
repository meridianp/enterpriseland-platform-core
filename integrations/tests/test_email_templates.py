"""
Tests for email templates integration with email service.
"""
import asyncio
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from accounts.models import Group
# TODO: Move these tests to investment module
# from contacts.models import EmailTemplate
from integrations.services.email import email_service
from integrations.testing import get_test_provider_config

User = get_user_model()


def run_async_test(coro):
    """Helper to run async tests in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@override_settings(PROVIDER_CONFIG=get_test_provider_config())
# TODO: These tests are specific to the investment module and should be moved there
# class TestEmailTemplates(TestCase):
    """Test email templates with the email service."""
    
    def setUp(self):
        """Set up test data."""
        # Create test group and user
        self.group = Group.objects.create(name='test_group')
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.group = self.group
        self.user.save()
        
        # Create test template
        self.template = EmailTemplate.objects.create(
            group=self.group,
            name='Test Welcome Email',
            slug='test-welcome',
            template_type=EmailTemplate.TemplateType.TRANSACTIONAL,
            subject='Welcome {{ first_name }}!',
            preheader='Get started with your account',
            html_content='''
                <h1>Welcome {{ first_name }}!</h1>
                <p>Thanks for joining {{ company_name }}.</p>
                <p>Your email is: {{ email }}</p>
                <a href="{{ login_url }}">Login Now</a>
            ''',
            text_content='''
                Welcome {{ first_name }}!
                Thanks for joining {{ company_name }}.
                Your email is: {{ email }}
                Login at: {{ login_url }}
            ''',
            from_name='Test Company',
            from_email='noreply@test.com',
            available_variables=['first_name', 'email', 'company_name', 'login_url'],
            is_active=True
        )
    
    def test_send_email_with_template(self):
        """Test sending email using database template."""
        result = run_async_test(email_service.send_email(
            to='recipient@example.com',
            subject=None,  # Will be taken from template
            template_id='test-welcome',
            template_data={
                'first_name': 'John',
                'email': 'john@example.com',
                'company_name': 'Acme Corp',
                'login_url': 'https://app.example.com/login'
            }
        ))
        
        self.assertTrue(result.success)
        self.assertIsNotNone(result.message_id)
        
        # Check that mock provider received the email
        from integrations.testing import MockEmailProvider
        provider = email_service.provider_registry.get_provider('email', 'mock')
        self.assertIsInstance(provider, MockEmailProvider)
        
        sent_messages = provider.get_sent_messages()
        self.assertEqual(len(sent_messages), 1)
        
        message = sent_messages[0]
        self.assertEqual(message.to, ['recipient@example.com'])
        self.assertEqual(message.subject, 'Welcome John!')
        self.assertIn('Welcome John!', message.html_content)
        self.assertIn('Thanks for joining Acme Corp', message.html_content)
        self.assertIn('john@example.com', message.html_content)
        self.assertEqual(message.from_name, 'Test Company')
        self.assertEqual(message.from_email, 'noreply@test.com')
    
    def test_send_bulk_with_template(self):
        """Test sending bulk emails with template."""
        messages = [
            {
                'to': 'user1@example.com',
                'template_data': {
                    'first_name': 'Alice',
                    'email': 'alice@example.com'
                }
            },
            {
                'to': 'user2@example.com',
                'template_data': {
                    'first_name': 'Bob',
                    'email': 'bob@example.com'
                }
            }
        ]
        
        result = run_async_test(email_service.send_bulk(
            messages=messages,
            template_id='test-welcome',
            base_template_data={
                'company_name': 'EnterpriseLand',
                'login_url': 'https://app.enterpriseland.com/login'
            }
        ))
        
        self.assertEqual(result.total, 2)
        self.assertEqual(result.successful, 2)
        self.assertEqual(result.failed, 0)
        
        # Verify emails were personalized
        provider = email_service.provider_registry.get_provider('email', 'mock')
        sent_messages = provider.get_sent_messages()
        
        # Find Alice's email
        alice_email = next(m for m in sent_messages if m.to[0] == 'user1@example.com')
        self.assertEqual(alice_email.subject, 'Welcome Alice!')
        self.assertIn('alice@example.com', alice_email.html_content)
        
        # Find Bob's email
        bob_email = next(m for m in sent_messages if m.to[0] == 'user2@example.com')
        self.assertEqual(bob_email.subject, 'Welcome Bob!')
        self.assertIn('bob@example.com', bob_email.html_content)
    
    def test_template_with_missing_variables(self):
        """Test template rendering with missing variables."""
        result = run_async_test(email_service.send_email(
            to='recipient@example.com',
            subject=None,
            template_id='test-welcome',
            template_data={
                'first_name': 'Jane'
                # Missing: email, company_name, login_url
            }
        ))
        
        # Should still succeed, with empty values for missing vars
        self.assertTrue(result.success)
        
        provider = email_service.provider_registry.get_provider('email', 'mock')
        sent_messages = provider.get_sent_messages()
        message = sent_messages[-1]
        
        self.assertEqual(message.subject, 'Welcome Jane!')
        # Jinja2 renders missing variables as empty strings
        self.assertIn('Your email is: ', message.html_content)
    
    def test_template_not_found(self):
        """Test error when template doesn't exist."""
        with self.assertRaises(ValueError) as context:
            run_async_test(email_service.send_email(
                to='recipient@example.com',
                subject=None,
                template_id='non-existent-template'
            ))
        
        self.assertIn("Email template 'non-existent-template' not found", str(context.exception))
    
    def test_inactive_template(self):
        """Test that inactive templates are not found."""
        # Deactivate template
        self.template.is_active = False
        self.template.save()
        
        with self.assertRaises(ValueError) as context:
            run_async_test(email_service.send_email(
                to='recipient@example.com',
                subject=None,
                template_id='test-welcome'
            ))
        
        self.assertIn("Email template 'test-welcome' not found", str(context.exception))
    
    def test_template_caching(self):
        """Test that templates are cached."""
        # First call should load from database
        result1 = run_async_test(email_service.send_email(
            to='user1@example.com',
            subject=None,
            template_id='test-welcome',
            template_data={'first_name': 'User1'}
        ))
        self.assertTrue(result1.success)
        
        # Update template in database
        self.template.subject = 'Updated: {{ first_name }}'
        self.template.save()
        
        # Second call should use cached version
        result2 = run_async_test(email_service.send_email(
            to='user2@example.com',
            subject=None,
            template_id='test-welcome',
            template_data={'first_name': 'User2'}
        ))
        self.assertTrue(result2.success)
        
        # Check that cached version was used (old subject)
        provider = email_service.provider_registry.get_provider('email', 'mock')
        sent_messages = provider.get_sent_messages()
        
        # Both should have the original subject
        user2_email = next(m for m in sent_messages if m.to[0] == 'user2@example.com')
        self.assertEqual(user2_email.subject, 'Welcome User2!')  # Not "Updated: User2"
    
    def test_responsive_email_template(self):
        """Test that responsive HTML is processed correctly."""
        # Create a template with CSS that should be inlined
        responsive_template = EmailTemplate.objects.create(
            group=self.group,
            name='Responsive Test',
            slug='responsive-test',
            template_type=EmailTemplate.TemplateType.MARKETING,
            subject='Responsive Email Test',
            html_content='''
                <style>
                    .button { 
                        background-color: #007bff; 
                        color: white; 
                        padding: 10px 20px; 
                        text-decoration: none;
                        border-radius: 5px;
                    }
                    @media only screen and (max-width: 600px) {
                        .container { width: 100% !important; }
                    }
                </style>
                <div class="container">
                    <h1>Hello {{ name }}!</h1>
                    <a href="{{ url }}" class="button">Click Me</a>
                </div>
            ''',
            text_content='Hello {{ name }}! Visit: {{ url }}',
            is_active=True
        )
        
        result = run_async_test(email_service.send_email(
            to='recipient@example.com',
            subject=None,
            template_id='responsive-test',
            template_data={
                'name': 'Tester',
                'url': 'https://example.com'
            }
        ))
        
        self.assertTrue(result.success)
        
        # Check that CSS was processed
        provider = email_service.provider_registry.get_provider('email', 'mock')
        sent_messages = provider.get_sent_messages()
        message = sent_messages[-1]
        
        # CSS should be inlined (premailer converts classes to inline styles)
        self.assertIn('style=', message.html_content)
        self.assertIn('Hello Tester!', message.html_content)