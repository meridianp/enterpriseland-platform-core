"""
Unified email service using provider abstraction.

This service provides a high-level interface for sending emails with
automatic provider failover, template rendering, and tracking.
"""
import logging
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
import asyncio
from dataclasses import dataclass
from django.conf import settings
from django.core.cache import cache
from django.template import Template, Context
from django.utils import timezone
from asgiref.sync import sync_to_async

from jinja2 import Environment, BaseLoader, TemplateNotFound
from premailer import transform

from ..registry import provider_registry
from ..providers.email.base import (
    EmailMessage, SendResult, BulkSendResult, EmailEvent, EmailStatus
)
from ..exceptions import AllProvidersFailedError
from ..template_loaders import get_template_loader

logger = logging.getLogger(__name__)


class DatabaseTemplateLoader(BaseLoader):
    """Jinja2 template loader that loads from platform template loader."""
    
    def get_source(self, environment, template):
        """Load template from configured template loader."""
        loader = get_template_loader()
        template_data = loader.get_template(template)
        
        if template_data:
            source = template_data.get('html_content', '')
            # Return source, filename (None for DB), and uptodate function
            return source, None, lambda: True
        else:
            raise TemplateNotFound(template)


@dataclass
class EmailTemplate:
    """Email template data."""
    subject: str
    html_content: str
    text_content: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None


class EmailService:
    """
    High-level email service with provider abstraction.
    
    Features:
    - Automatic provider failover
    - Template rendering with Jinja2
    - CSS inlining for better email client support
    - Activity tracking
    - Caching for templates
    """
    
    def __init__(self):
        """Initialize email service."""
        self.provider_registry = provider_registry
        self.template_cache_ttl = getattr(settings, 'EMAIL_TEMPLATE_CACHE_TTL', 3600)
        
        # Initialize Jinja2 environment
        self.jinja_env = Environment(
            loader=DatabaseTemplateLoader(),
            autoescape=True
        )
        
        # Add custom filters
        self.jinja_env.filters['default'] = lambda x, d: x if x else d
        self.jinja_env.filters['title'] = lambda x: x.title() if x else ''
        self.jinja_env.filters['upper'] = lambda x: x.upper() if x else ''
        self.jinja_env.filters['lower'] = lambda x: x.lower() if x else ''
    
    async def send_email(
        self,
        to: Union[str, List[str]],
        subject: str,
        html_content: Optional[str] = None,
        text_content: Optional[str] = None,
        template_id: Optional[str] = None,
        template_data: Optional[Dict[str, Any]] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        campaign_id: Optional[str] = None,
        track_opens: bool = True,
        track_clicks: bool = True,
        send_at: Optional[datetime] = None,
        force_provider: Optional[str] = None
    ) -> SendResult:
        """
        Send a single email with automatic provider failover.
        
        Args:
            to: Recipient email(s)
            subject: Email subject
            html_content: HTML content (optional if template_id provided)
            text_content: Plain text content
            template_id: Template ID/slug for database templates
            template_data: Data for template rendering
            from_email: Sender email
            from_name: Sender name
            cc: CC recipients
            bcc: BCC recipients
            reply_to: Reply-to address
            attachments: List of attachments
            tags: Email tags for categorization
            metadata: Custom metadata
            campaign_id: Campaign identifier
            track_opens: Track email opens
            track_clicks: Track link clicks
            send_at: Schedule sending time
            force_provider: Force specific provider (bypasses failover)
            
        Returns:
            SendResult with success status and message ID
        """
        # Ensure to is a list
        if isinstance(to, str):
            to = [to]
        
        # Render template if provided
        if template_id:
            template = await self._get_template(template_id)
            
            # Render content
            context_data = template_data or {}
            if not html_content:
                html_content = await self._render_template(
                    template.html_content,
                    context_data
                )
            if not text_content and template.text_content:
                text_content = await self._render_template(
                    template.text_content,
                    context_data
                )
            
            # Use template defaults if not overridden
            subject = subject or await self._render_template(
                template.subject,
                context_data
            )
            from_email = from_email or template.from_email
            from_name = from_name or template.from_name
            reply_to = reply_to or template.reply_to
        
        # Process HTML content (inline CSS)
        if html_content:
            html_content = await self._process_html(html_content)
        
        # Create email message
        message = EmailMessage(
            to=to,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            from_email=from_email,
            from_name=from_name,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            attachments=attachments,
            tags=tags,
            metadata=metadata,
            campaign_id=campaign_id,
            track_opens=track_opens,
            track_clicks=track_clicks,
            send_at=send_at
        )
        
        # Send with provider
        if force_provider:
            # Use specific provider
            provider = self.provider_registry.get_provider('email', force_provider)
            result = await provider.send(message)
        else:
            # Use automatic failover
            try:
                result = await self.provider_registry.execute(
                    service='email',
                    operation='send',
                    message=message
                )
            except AllProvidersFailedError as e:
                logger.error(f"All email providers failed: {e}")
                # Return failure result
                return SendResult(
                    success=False,
                    error_code="ALL_PROVIDERS_FAILED",
                    error_message=str(e),
                    provider=None
                )
        
        # Track activity
        if result.success:
            await self._track_email_sent(message, result)
        
        return result
    
    async def send_bulk(
        self,
        messages: List[Dict[str, Any]],
        template_id: Optional[str] = None,
        base_template_data: Optional[Dict[str, Any]] = None,
        force_provider: Optional[str] = None
    ) -> BulkSendResult:
        """
        Send multiple emails with automatic provider failover.
        
        Args:
            messages: List of message data (each with to, subject, etc.)
            template_id: Common template for all messages
            base_template_data: Base template data (merged with each message's data)
            force_provider: Force specific provider
            
        Returns:
            BulkSendResult with success/failure counts
        """
        email_messages = []
        
        # Get template if provided
        template = None
        if template_id:
            template = await self._get_template(template_id)
        
        # Build email messages
        for msg_data in messages:
            # Merge template data
            template_data = {**(base_template_data or {}), **(msg_data.get('template_data', {}))}
            
            # Get content
            html_content = msg_data.get('html_content')
            text_content = msg_data.get('text_content')
            subject = msg_data.get('subject')
            
            # Render from template if needed
            if template and not html_content:
                html_content = await self._render_template(
                    template.html_content,
                    template_data
                )
            if template and not text_content and template.text_content:
                text_content = await self._render_template(
                    template.text_content,
                    template_data
                )
            if template and not subject:
                subject = await self._render_template(
                    template.subject,
                    template_data
                )
            
            # Process HTML
            if html_content:
                html_content = await self._process_html(html_content)
            
            # Create message
            to = msg_data.get('to')
            if isinstance(to, str):
                to = [to]
            
            message = EmailMessage(
                to=to,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                from_email=msg_data.get('from_email', template.from_email if template else None),
                from_name=msg_data.get('from_name', template.from_name if template else None),
                cc=msg_data.get('cc'),
                bcc=msg_data.get('bcc'),
                reply_to=msg_data.get('reply_to', template.reply_to if template else None),
                attachments=msg_data.get('attachments'),
                tags=msg_data.get('tags'),
                metadata=msg_data.get('metadata'),
                campaign_id=msg_data.get('campaign_id'),
                track_opens=msg_data.get('track_opens', True),
                track_clicks=msg_data.get('track_clicks', True),
                send_at=msg_data.get('send_at')
            )
            
            email_messages.append(message)
        
        # Send with provider
        if force_provider:
            provider = self.provider_registry.get_provider('email', force_provider)
            result = await provider.send_bulk(email_messages)
        else:
            try:
                result = await self.provider_registry.execute(
                    service='email',
                    operation='send_bulk',
                    messages=email_messages
                )
            except AllProvidersFailedError as e:
                logger.error(f"All email providers failed for bulk send: {e}")
                # Return failure result
                return BulkSendResult(
                    total=len(email_messages),
                    successful=0,
                    failed=len(email_messages),
                    results=[],
                    provider=None
                )
        
        return result
    
    async def send_transactional(
        self,
        to: Union[str, List[str]],
        template_slug: str,
        context: Dict[str, Any],
        **kwargs
    ) -> SendResult:
        """
        Send a transactional email using a pre-defined template.
        
        Common transactional emails:
        - welcome: Welcome email for new users
        - password-reset: Password reset instructions
        - assessment-submitted: Assessment submission confirmation
        - assessment-completed: Assessment completion notification
        - lead-assigned: Lead assignment notification
        
        Args:
            to: Recipient email(s)
            template_slug: Template identifier
            context: Template context data
            **kwargs: Additional email options
            
        Returns:
            SendResult
        """
        # Add system context
        context.update({
            'app_name': getattr(settings, 'APP_NAME', 'EnterpriseLand'),
            'app_url': getattr(settings, 'FRONTEND_URL', 'http://localhost:3000'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@example.com'),
            'current_year': datetime.now().year,
            'current_date': datetime.now().strftime('%B %d, %Y')
        })
        
        return await self.send_email(
            to=to,
            template_id=template_slug,
            template_data=context,
            tags=['transactional', template_slug],
            **kwargs
        )
    
    async def process_webhook(
        self,
        provider_name: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> List[EmailEvent]:
        """
        Process webhook data from email provider.
        
        Args:
            provider_name: Name of the provider
            data: Webhook payload
            headers: HTTP headers (for signature validation)
            
        Returns:
            List of EmailEvent objects
        """
        try:
            provider = self.provider_registry.get_provider('email', provider_name)
            
            # Validate webhook signature if supported
            if hasattr(provider, 'validate_webhook_signature') and headers:
                # Provider-specific signature validation
                # This varies by provider
                pass
            
            # Process webhook data
            events = await provider.process_webhook(data)
            
            # Track events
            for event in events:
                await self._track_email_event(event)
            
            return events
            
        except Exception as e:
            logger.error(f"Error processing webhook from {provider_name}: {str(e)}")
            return []
    
    async def get_provider_health(self) -> Dict[str, Dict[str, Any]]:
        """
        Get health status of all email providers.
        
        Returns:
            Dict with provider health information
        """
        providers = self.provider_registry.get_available_providers('email')
        health_status = {}
        
        for provider_name in providers:
            provider = self.provider_registry.get_provider('email', provider_name)
            
            # Get health status
            try:
                is_healthy = await provider.health_check()
            except:
                is_healthy = False
            
            # Get circuit breaker state
            cb_state = self.provider_registry.get_circuit_breaker_states().get(
                f'email.{provider_name}',
                {}
            )
            
            # Get metrics
            metrics = self.provider_registry.get_provider_metrics().get('email', {}).get(provider_name, {})
            
            health_status[provider_name] = {
                'healthy': is_healthy,
                'circuit_breaker': cb_state,
                'metrics': metrics
            }
        
        return health_status
    
    async def _get_template(self, template_id: str) -> EmailTemplate:
        """Get email template from cache or template loader."""
        cache_key = f'email_template:{template_id}'
        cached = cache.get(cache_key)
        
        if cached:
            return EmailTemplate(**cached)
        
        # Load from template loader
        loader = get_template_loader()
        template_data = await sync_to_async(loader.get_template)(template_id)
        
        if not template_data:
            raise ValueError(f"Email template '{template_id}' not found")
        
        try:
            template = EmailTemplate(
                subject=template_data.get('subject', ''),
                html_content=template_data.get('html_content', ''),
                text_content=template_data.get('text_content', ''),
                from_email=template_data.get('from_email', settings.DEFAULT_FROM_EMAIL),
                from_name=template_data.get('from_name', ''),
                reply_to=template_data.get('reply_to', '')
            )
            
            # Cache template
            cache.set(
                cache_key,
                {
                    'subject': template.subject,
                    'html_content': template.html_content,
                    'text_content': template.text_content,
                    'from_email': template.from_email,
                    'from_name': template.from_name,
                    'reply_to': template.reply_to
                },
                self.template_cache_ttl
            )
            
            return template
            
        except Exception as e:
            raise ValueError(f"Email template '{template_id}' not found: {str(e)}")
    
    async def _render_template(self, template_str: str, context: Dict[str, Any]) -> str:
        """Render template with Jinja2."""
        try:
            # Use Jinja2 for rendering
            template = self.jinja_env.from_string(template_str)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering error: {str(e)}")
            # Fallback to Django template
            template = Template(template_str)
            return template.render(Context(context))
    
    async def _process_html(self, html_content: str) -> str:
        """Process HTML content for email compatibility."""
        try:
            # Inline CSS using premailer
            processed = transform(
                html_content,
                base_url=getattr(settings, 'FRONTEND_URL', None),
                preserve_internal_links=True,
                exclude_pseudoclasses=True,
                keep_style_tags=True,
                include_star_selectors=False
            )
            return processed
        except Exception as e:
            logger.warning(f"CSS inlining failed: {str(e)}")
            return html_content
    
    async def _track_email_sent(self, message: EmailMessage, result: SendResult):
        """Track email sent activity."""
        # TODO: Implement activity tracking
        # This would typically create records in the database
        pass
    
    async def _track_email_event(self, event: EmailEvent):
        """Track email event (open, click, bounce, etc.)."""
        # TODO: Implement event tracking
        # This would typically update message status in the database
        pass


# Global email service instance
email_service = EmailService()