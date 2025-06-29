"""
Mailgun email provider implementation.

Provides integration with Mailgun's API for sending transactional
and marketing emails with advanced features like batch sending and analytics.
"""
import logging
import json
import base64
from typing import List, Optional, Dict, Any
from datetime import datetime
import hashlib
import hmac

import requests
from requests.auth import HTTPBasicAuth

from ..base import ProviderConfig
from .base import (
    EmailProvider, EmailMessage, SendResult, BulkSendResult,
    EmailStatus, EmailEvent, EmailAttachment
)

logger = logging.getLogger(__name__)


class MailgunProvider(EmailProvider):
    """Mailgun email provider implementation."""
    
    def __init__(self, config: ProviderConfig):
        """Initialize Mailgun provider."""
        super().__init__(config)
        self.api_key = config.params.get('api_key')
        self.domain = config.params.get('domain')
        self.eu_region = config.params.get('eu_region', False)
        self.webhook_signing_key = config.params.get('webhook_signing_key', '')
        
        # Default sender
        self.from_email = config.params.get('from_email', 'noreply@example.com')
        self.from_name = config.params.get('from_name', 'EnterpriseLand')
        
        # API base URL
        if self.eu_region:
            self.base_url = 'https://api.eu.mailgun.net/v3'
        else:
            self.base_url = 'https://api.mailgun.net/v3'
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth('api', self.api_key)
        
        # Tracking settings
        self.track_opens = config.params.get('track_opens', True)
        self.track_clicks = config.params.get('track_clicks', True)
        self.track_unsubscribes = config.params.get('track_unsubscribes', True)
    
    async def execute(self, **kwargs):
        """Execute email sending operation."""
        if 'messages' in kwargs:
            return await self.send_bulk(kwargs['messages'])
        else:
            message = EmailMessage(**kwargs)
            return await self.send(message)
    
    async def send(self, message: EmailMessage) -> SendResult:
        """Send a single email message using Mailgun API."""
        # Validate message
        message.validate()
        
        try:
            # Build request data
            data = self._build_mailgun_data(message)
            files = self._build_attachments(message)
            
            # Send email
            response = self.session.post(
                f"{self.base_url}/{self.domain}/messages",
                data=data,
                files=files,
                timeout=30
            )
            
            if response.status_code == 200:
                result_data = response.json()
                return SendResult(
                    success=True,
                    message_id=result_data.get('id', '').strip('<>'),
                    provider="mailgun",
                    metadata={
                        "message": result_data.get('message'),
                        "queued": True
                    }
                )
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                return SendResult(
                    success=False,
                    error_code=str(response.status_code),
                    error_message=error_data.get('message', response.text),
                    provider="mailgun"
                )
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Mailgun request error: {str(e)}")
            return SendResult(
                success=False,
                error_code="REQUEST_ERROR",
                error_message=str(e),
                provider="mailgun"
            )
        except Exception as e:
            logger.error(f"Mailgun provider error: {str(e)}")
            return SendResult(
                success=False,
                error_code="PROVIDER_ERROR",
                error_message=str(e),
                provider="mailgun"
            )
        finally:
            # Clean up file handles
            if 'files' in locals() and files:
                for _, file_tuple in files:
                    if hasattr(file_tuple[1], 'close'):
                        file_tuple[1].close()
    
    async def send_bulk(self, messages: List[EmailMessage]) -> BulkSendResult:
        """
        Send multiple emails using Mailgun's batch API.
        
        Mailgun supports recipient variables for personalization.
        """
        if not messages:
            return BulkSendResult(
                total=0,
                successful=0,
                failed=0,
                results=[],
                provider="mailgun"
            )
        
        # Group messages by content for batch optimization
        # For now, send individually
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
            provider="mailgun"
        )
    
    async def send_batch_personalized(
        self,
        base_message: EmailMessage,
        recipients: List[Dict[str, Any]]
    ) -> SendResult:
        """
        Send personalized emails to multiple recipients in one API call.
        
        Uses Mailgun's recipient variables for personalization.
        """
        try:
            # Build base data
            data = self._build_mailgun_data(base_message)
            
            # Build recipient variables
            recipient_vars = {}
            to_list = []
            
            for recipient in recipients:
                email = recipient.get('email')
                if email:
                    to_list.append(email)
                    recipient_vars[email] = recipient.get('variables', {})
            
            # Update data with batch information
            data['to'] = to_list
            data['recipient-variables'] = json.dumps(recipient_vars)
            
            # Send batch email
            response = self.session.post(
                f"{self.base_url}/{self.domain}/messages",
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result_data = response.json()
                return SendResult(
                    success=True,
                    message_id=result_data.get('id', '').strip('<>'),
                    provider="mailgun",
                    metadata={
                        "message": result_data.get('message'),
                        "recipient_count": len(to_list)
                    }
                )
            else:
                return SendResult(
                    success=False,
                    error_code=str(response.status_code),
                    error_message=response.text,
                    provider="mailgun"
                )
                
        except Exception as e:
            logger.error(f"Mailgun batch send error: {str(e)}")
            return SendResult(
                success=False,
                error_code="BATCH_ERROR",
                error_message=str(e),
                provider="mailgun"
            )
    
    async def get_message_events(
        self,
        message_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get events for messages.
        
        Can filter by message ID or event type.
        """
        try:
            params = {
                'limit': limit,
                'ascending': 'no'
            }
            
            if message_id:
                params['message-id'] = message_id
            
            if event_type:
                params['event'] = event_type
            
            response = self.session.get(
                f"{self.base_url}/{self.domain}/events",
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('items', [])
            else:
                logger.error(f"Failed to get events: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Mailgun events: {str(e)}")
            return []
    
    async def process_webhook(self, data: Dict[str, Any]) -> List[EmailEvent]:
        """
        Process webhook data from Mailgun.
        
        Mailgun sends individual events via webhooks.
        """
        events = []
        
        try:
            event_type = data.get('event', '').lower()
            
            # Map Mailgun events to our EmailStatus
            status_map = {
                'accepted': EmailStatus.SENT,
                'delivered': EmailStatus.DELIVERED,
                'opened': EmailStatus.OPENED,
                'clicked': EmailStatus.CLICKED,
                'unsubscribed': EmailStatus.UNSUBSCRIBED,
                'complained': EmailStatus.SPAM,
                'failed': EmailStatus.FAILED,
                'rejected': EmailStatus.FAILED,
                'stored': EmailStatus.PENDING
            }
            
            if event_type in status_map:
                # Get timestamp
                timestamp = data.get('timestamp', 0)
                if timestamp:
                    timestamp = datetime.fromtimestamp(float(timestamp))
                else:
                    timestamp = datetime.now()
                
                event = EmailEvent(
                    message_id=data.get('message-id', '').strip('<>'),
                    event_type=status_map[event_type],
                    timestamp=timestamp,
                    recipient=data.get('recipient'),
                    user_agent=data.get('client-info', {}).get('user-agent'),
                    ip_address=data.get('ip'),
                    url=data.get('url'),  # For click events
                    reason=data.get('reason') or data.get('error'),  # For failures
                    provider="mailgun",
                    raw_data=data
                )
                
                events.append(event)
                
        except Exception as e:
            logger.error(f"Error processing Mailgun webhook: {str(e)}")
        
        return events
    
    async def validate_webhook_signature(
        self,
        timestamp: str,
        token: str,
        signature: str
    ) -> bool:
        """
        Validate webhook signature from Mailgun.
        
        Mailgun uses HMAC-SHA256 with timestamp and token.
        """
        if not self.webhook_signing_key:
            logger.warning("No webhook signing key configured for Mailgun")
            return True  # Allow if no key is configured
        
        # Construct the string to sign
        signed_data = f"{timestamp}{token}"
        
        # Calculate expected signature
        expected_signature = hmac.new(
            self.webhook_signing_key.encode(),
            signed_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(expected_signature, signature)
    
    async def validate_domain(self, domain: str) -> bool:
        """
        Check if a domain is verified with Mailgun.
        """
        try:
            response = self.session.get(
                f"{self.base_url}/domains/{domain}",
                timeout=30
            )
            
            if response.status_code == 200:
                domain_data = response.json()
                domain_info = domain_data.get('domain', {})
                
                # Check if domain is active and verified
                state = domain_info.get('state', '')
                return state == 'active'
            
            return False
            
        except Exception as e:
            logger.error(f"Error validating domain with Mailgun: {str(e)}")
            return False
    
    async def get_stats(
        self,
        event: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get statistics from Mailgun."""
        try:
            params = {}
            
            if event:
                params['event'] = event
            
            if start:
                params['start'] = start.strftime('%a, %d %b %Y %H:%M:%S UTC')
            
            if end:
                params['end'] = end.strftime('%a, %d %b %Y %H:%M:%S UTC')
            
            response = self.session.get(
                f"{self.base_url}/{self.domain}/stats/total",
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get stats: {response.status_code}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting Mailgun stats: {str(e)}")
            return {}
    
    async def health_check(self) -> bool:
        """Check if Mailgun API is accessible."""
        if not self.api_key or not self.domain:
            return False
        
        try:
            # Try to get domain info as a health check
            response = self.session.get(
                f"{self.base_url}/domains/{self.domain}",
                timeout=10
            )
            return response.status_code in [200, 401]  # 401 means API is up but key may be invalid
        except Exception as e:
            logger.error(f"Mailgun health check failed: {str(e)}")
            return False
    
    def _build_mailgun_data(self, message: EmailMessage) -> Dict[str, Any]:
        """Build Mailgun API request data from EmailMessage."""
        data = {
            'from': f"{message.from_name or self.from_name} <{message.from_email or self.from_email}>",
            'to': message.to,
            'subject': message.subject
        }
        
        # CC and BCC
        if message.cc:
            data['cc'] = message.cc
        
        if message.bcc:
            data['bcc'] = message.bcc
        
        # Reply-to
        if message.reply_to:
            data['h:Reply-To'] = message.reply_to
        
        # Content
        if message.text_content:
            data['text'] = message.text_content
        
        if message.html_content:
            data['html'] = message.html_content
        
        # Tags (Mailgun supports up to 3 tags)
        if message.tags:
            for i, tag in enumerate(message.tags[:3]):
                data[f'o:tag'] = tag
        
        # Custom headers
        if message.headers:
            for key, value in message.headers.items():
                data[f'h:{key}'] = value
        
        # Campaign ID
        if message.campaign_id:
            data['o:campaign'] = str(message.campaign_id)
            data['v:campaign_id'] = str(message.campaign_id)
        
        # Custom variables for tracking
        if message.metadata:
            for key, value in message.metadata.items():
                data[f'v:{key}'] = str(value)
        
        # Tracking options
        data['o:tracking'] = 'yes' if (self.track_opens or message.track_opens) else 'no'
        data['o:tracking-clicks'] = 'yes' if (self.track_clicks or message.track_clicks) else 'no'
        data['o:tracking-opens'] = 'yes' if (self.track_opens or message.track_opens) else 'no'
        
        # Schedule sending
        if message.send_at:
            data['o:deliverytime'] = message.send_at.strftime('%a, %d %b %Y %H:%M:%S %z')
        
        # Template support (using Mailgun templates)
        if message.template_id:
            data['template'] = message.template_id
            if message.template_data:
                data['h:X-Mailgun-Variables'] = json.dumps(message.template_data)
        
        return data
    
    def _build_attachments(self, message: EmailMessage) -> List[tuple]:
        """Build attachment list for Mailgun API."""
        if not message.attachments:
            return []
        
        files = []
        
        for attachment in message.attachments:
            # Mailgun expects file-like objects
            if isinstance(attachment.content, bytes):
                from io import BytesIO
                file_obj = BytesIO(attachment.content)
            else:
                file_obj = attachment.content
            
            # Add as attachment or inline
            if attachment.disposition == 'inline' and attachment.content_id:
                files.append(('inline', (attachment.filename, file_obj, attachment.content_type)))
            else:
                files.append(('attachment', (attachment.filename, file_obj, attachment.content_type)))
        
        return files