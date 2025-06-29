"""
SendGrid email provider implementation.

Provides full integration with SendGrid's API for sending transactional
and marketing emails with tracking, templates, and webhooks.
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import hashlib
import hmac

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Email, To, Content, Attachment, FileContent, FileName,
    FileType, Disposition, ContentId, TrackingSettings, ClickTracking,
    OpenTracking, SubscriptionTracking, Ganalytics, Substitution,
    CustomArg, ReplyTo, Category, BatchId, Asm, GroupId, GroupsToDisplay,
    MailSettings, BccSettings, FooterSettings, SandBoxMode
)
from python_http_client.exceptions import HTTPError

from ..base import ProviderConfig
from .base import (
    EmailProvider, EmailMessage, SendResult, BulkSendResult,
    EmailStatus, EmailEvent, EmailAttachment
)

logger = logging.getLogger(__name__)


class SendGridProvider(EmailProvider):
    """SendGrid email provider implementation."""
    
    def __init__(self, config: ProviderConfig):
        """Initialize SendGrid provider."""
        super().__init__(config)
        self.api_key = config.params.get('api_key')
        self.from_email = config.params.get('from_email', 'noreply@example.com')
        self.from_name = config.params.get('from_name', 'EnterpriseLand')
        self.webhook_secret = config.params.get('webhook_secret', '')
        self.sandbox_mode = config.params.get('sandbox_mode', False)
        
        # Initialize SendGrid client
        self.client = SendGridAPIClient(api_key=self.api_key)
        
        # Track settings
        self.track_opens = config.params.get('track_opens', True)
        self.track_clicks = config.params.get('track_clicks', True)
        self.track_subscriptions = config.params.get('track_subscriptions', True)
    
    async def execute(self, **kwargs):
        """Execute email sending operation."""
        # Delegate to the appropriate method
        if 'messages' in kwargs:
            return await self.send_bulk(kwargs['messages'])
        else:
            # Build EmailMessage from kwargs
            message = EmailMessage(**kwargs)
            return await self.send(message)
    
    async def send(self, message: EmailMessage) -> SendResult:
        """Send a single email message using SendGrid API."""
        # Validate message
        message.validate()
        
        try:
            # Create SendGrid Mail object
            mail = self._build_mail_object(message)
            
            # Send the email
            response = self.client.send(mail)
            
            # Extract message ID from response headers
            message_id = None
            if hasattr(response, 'headers') and 'X-Message-Id' in response.headers:
                message_id = response.headers['X-Message-Id']
            
            return SendResult(
                success=True,
                message_id=message_id or f"sendgrid-{response.status_code}-{hash(message.to[0])}",
                provider="sendgrid",
                metadata={
                    "status_code": response.status_code,
                    "headers": dict(response.headers) if hasattr(response, 'headers') else {}
                }
            )
            
        except HTTPError as e:
            logger.error(f"SendGrid API error: {e.status_code} - {e.body}")
            return SendResult(
                success=False,
                error_code=str(e.status_code),
                error_message=str(e.body),
                provider="sendgrid"
            )
        except Exception as e:
            logger.error(f"SendGrid provider error: {str(e)}")
            return SendResult(
                success=False,
                error_code="PROVIDER_ERROR",
                error_message=str(e),
                provider="sendgrid"
            )
    
    async def send_bulk(self, messages: List[EmailMessage]) -> BulkSendResult:
        """
        Send multiple emails using SendGrid's batch send API.
        
        For better performance, SendGrid recommends using personalizations
        for sending to multiple recipients with the same content.
        """
        if not messages:
            return BulkSendResult(
                total=0,
                successful=0,
                failed=0,
                results=[],
                provider="sendgrid"
            )
        
        # Group messages by template/content for batch optimization
        # For now, send individually (can be optimized later)
        results = []
        successful = 0
        failed = 0
        
        for message in messages:
            result = await self.send(message)
            results.append(result)
            if result.success:
                successful += 1
            else:
                failed += 1
        
        return BulkSendResult(
            total=len(messages),
            successful=successful,
            failed=failed,
            results=results,
            provider="sendgrid"
        )
    
    async def get_message_status(self, message_id: str) -> Optional[EmailStatus]:
        """
        Get the current status of a sent message.
        
        Note: SendGrid doesn't provide real-time message status via API.
        Status updates come through webhooks.
        """
        # SendGrid doesn't support direct message status lookup
        # Status tracking must be done via webhooks
        logger.warning("SendGrid doesn't support direct message status lookup. Use webhooks.")
        return None
    
    async def process_webhook(self, data: Dict[str, Any]) -> List[EmailEvent]:
        """
        Process webhook data from SendGrid.
        
        SendGrid sends webhook events for various email activities.
        """
        events = []
        
        # SendGrid sends an array of events
        if isinstance(data, list):
            webhook_events = data
        else:
            webhook_events = [data]
        
        for event_data in webhook_events:
            event_type = event_data.get('event', '').lower()
            
            # Map SendGrid events to our EmailStatus
            status_map = {
                'processed': EmailStatus.SENT,
                'delivered': EmailStatus.DELIVERED,
                'open': EmailStatus.OPENED,
                'click': EmailStatus.CLICKED,
                'bounce': EmailStatus.BOUNCED,
                'dropped': EmailStatus.FAILED,
                'spamreport': EmailStatus.SPAM,
                'unsubscribe': EmailStatus.UNSUBSCRIBED,
                'deferred': EmailStatus.PENDING
            }
            
            if event_type in status_map:
                # Extract message ID from custom args or sg_message_id
                message_id = (
                    event_data.get('X-Message-ID') or 
                    event_data.get('sg_message_id') or
                    event_data.get('message_id')
                )
                
                if message_id:
                    event = EmailEvent(
                        message_id=message_id,
                        event_type=status_map[event_type],
                        timestamp=datetime.fromtimestamp(event_data.get('timestamp', 0)),
                        recipient=event_data.get('email'),
                        user_agent=event_data.get('useragent'),
                        ip_address=event_data.get('ip'),
                        url=event_data.get('url'),  # For click events
                        reason=event_data.get('reason'),  # For bounce events
                        provider="sendgrid",
                        raw_data=event_data
                    )
                    events.append(event)
        
        return events
    
    async def validate_webhook_signature(self, signature: str, timestamp: str, body: bytes) -> bool:
        """
        Validate webhook signature from SendGrid.
        
        SendGrid uses the Event Webhook Signing Key for HMAC-SHA256 signatures.
        """
        if not self.webhook_secret:
            logger.warning("No webhook secret configured for SendGrid provider")
            return True  # Allow if no secret is configured
        
        # Construct the payload
        payload = timestamp.encode() + body
        
        # Calculate expected signature
        expected_signature = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).digest()
        
        # Compare signatures
        provided_signature = signature.encode() if isinstance(signature, str) else signature
        return hmac.compare_digest(expected_signature, provided_signature)
    
    async def validate_domain(self, domain: str) -> bool:
        """
        Check if a domain is authenticated with SendGrid.
        
        This requires domain authentication to be set up in SendGrid.
        """
        try:
            # Get authenticated domains
            response = self.client.client.whitelabel.domains.get()
            
            if response.status_code == 200:
                domains = response.body.get('result', [])
                for d in domains:
                    if d.get('domain') == domain and d.get('valid'):
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error validating domain with SendGrid: {str(e)}")
            return False
    
    async def health_check(self) -> bool:
        """Check if SendGrid API is accessible."""
        if not self.api_key:
            return False
        
        try:
            # Use the API key validation endpoint
            response = self.client.client.api_keys.get()
            return response.status_code in [200, 401]  # 401 means API is up but key may be invalid
        except Exception as e:
            logger.error(f"SendGrid health check failed: {str(e)}")
            return False
    
    def _build_mail_object(self, message: EmailMessage) -> Mail:
        """Build SendGrid Mail object from EmailMessage."""
        # Create Mail object
        mail = Mail()
        
        # From email
        mail.from_email = Email(
            message.from_email or self.from_email,
            message.from_name or self.from_name
        )
        
        # Subject
        mail.subject = message.subject
        
        # To recipients
        mail.to = [To(email) for email in message.to]
        
        # CC recipients
        if message.cc:
            from sendgrid.helpers.mail import Cc
            for email in message.cc:
                mail.add_cc(Cc(email))
        
        # BCC recipients
        if message.bcc:
            from sendgrid.helpers.mail import Bcc
            for email in message.bcc:
                mail.add_bcc(Bcc(email))
        
        # Reply-to
        if message.reply_to:
            mail.reply_to = ReplyTo(message.reply_to)
        
        # Content
        if message.text_content:
            mail.content = [Content("text/plain", message.text_content)]
        
        if message.html_content:
            if mail.content:
                mail.content.append(Content("text/html", message.html_content))
            else:
                mail.content = [Content("text/html", message.html_content)]
        
        # Template support
        if message.template_id:
            mail.template_id = message.template_id
            
            # Add template data as substitutions
            if message.template_data:
                for key, value in message.template_data.items():
                    mail.add_substitution(Substitution(f"-{key}-", str(value)))
        
        # Attachments
        if message.attachments:
            for attachment in message.attachments:
                sendgrid_attachment = Attachment()
                sendgrid_attachment.file_content = FileContent(
                    attachment.content.decode('utf-8') if isinstance(attachment.content, bytes) 
                    else attachment.content
                )
                sendgrid_attachment.file_name = FileName(attachment.filename)
                sendgrid_attachment.file_type = FileType(attachment.content_type)
                sendgrid_attachment.disposition = Disposition(attachment.disposition)
                
                if attachment.content_id:
                    sendgrid_attachment.content_id = ContentId(attachment.content_id)
                
                mail.add_attachment(sendgrid_attachment)
        
        # Categories/Tags
        if message.tags:
            mail.category = [Category(tag) for tag in message.tags]
        
        # Custom args for tracking
        if message.metadata:
            for key, value in message.metadata.items():
                mail.add_custom_arg(CustomArg(key, str(value)))
        
        # Add message ID for webhook tracking
        if message.campaign_id:
            mail.add_custom_arg(CustomArg("campaign_id", str(message.campaign_id)))
            mail.add_custom_arg(CustomArg("X-Message-ID", str(message.campaign_id)))
        
        # Tracking settings
        mail.tracking_settings = TrackingSettings()
        
        if self.track_clicks or message.track_clicks:
            mail.tracking_settings.click_tracking = ClickTracking(
                enable=True,
                enable_text=True
            )
        
        if self.track_opens or message.track_opens:
            mail.tracking_settings.open_tracking = OpenTracking(enable=True)
        
        if self.track_subscriptions:
            mail.tracking_settings.subscription_tracking = SubscriptionTracking(
                enable=True,
                text="Unsubscribe",
                html="<a href='<%=unsubscribe_url%>'>Unsubscribe</a>"
            )
        
        # Mail settings
        mail.mail_settings = MailSettings()
        
        # Sandbox mode for testing
        if self.sandbox_mode:
            mail.mail_settings.sandbox_mode = SandBoxMode(enable=True)
        
        # Headers
        if message.headers:
            for key, value in message.headers.items():
                mail.add_header({key: value})
        
        # Schedule sending
        if message.send_at:
            mail.send_at = int(message.send_at.timestamp())
        
        return mail