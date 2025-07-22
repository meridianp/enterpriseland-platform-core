"""
Base classes for email service providers.
"""
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

from ..base import BaseProvider, ProviderConfig


class EmailStatus(Enum):
    """Email delivery status."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"
    SPAM = "spam"
    UNSUBSCRIBED = "unsubscribed"


@dataclass
class EmailAttachment:
    """Email attachment data."""
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"
    disposition: str = "attachment"
    content_id: Optional[str] = None  # For inline attachments


@dataclass
class EmailMessage:
    """Unified email message model for all email providers."""
    
    # Recipients
    to: List[str]
    subject: str
    
    # Content (at least one required)
    html_content: Optional[str] = None
    text_content: Optional[str] = None
    
    # Sender
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    
    # Additional recipients
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    reply_to: Optional[str] = None
    
    # Headers and metadata
    headers: Optional[Dict[str, str]] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    # Attachments
    attachments: Optional[List[EmailAttachment]] = None
    
    # Tracking
    track_opens: bool = True
    track_clicks: bool = True
    
    # Scheduling
    send_at: Optional[datetime] = None
    
    # Template support
    template_id: Optional[str] = None
    template_data: Optional[Dict[str, Any]] = None
    
    # Campaign/category
    campaign_id: Optional[str] = None
    category: Optional[str] = None
    
    def validate(self):
        """Validate the email message."""
        if not self.to:
            raise ValueError("Email must have at least one recipient")
        
        if not self.subject:
            raise ValueError("Email must have a subject")
        
        if not self.html_content and not self.text_content and not self.template_id:
            raise ValueError(
                "Email must have either html_content, text_content, or template_id"
            )


@dataclass
class SendResult:
    """Result of sending an email."""
    
    success: bool
    message_id: Optional[str] = None
    provider: Optional[str] = None
    
    # Error information
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    # Additional metadata
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class BulkSendResult:
    """Result of sending bulk emails."""
    
    total: int
    successful: int
    failed: int
    results: List[SendResult]
    provider: Optional[str] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        return self.successful / max(self.total, 1)


@dataclass
class EmailEvent:
    """Email event data for webhooks."""
    
    message_id: str
    event_type: EmailStatus
    timestamp: datetime
    
    # Event-specific data
    recipient: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    url: Optional[str] = None  # For click events
    reason: Optional[str] = None  # For bounce/failure events
    
    # Provider-specific data
    provider: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


class EmailProvider(BaseProvider):
    """Base class for all email service providers."""
    
    @abstractmethod
    async def send(self, message: EmailMessage) -> SendResult:
        """
        Send a single email message.
        
        Args:
            message: The email message to send
            
        Returns:
            SendResult indicating success/failure
        """
        pass
    
    async def send_bulk(self, messages: List[EmailMessage]) -> BulkSendResult:
        """
        Send multiple email messages.
        
        Default implementation sends individually.
        Providers can override for native bulk support.
        
        Args:
            messages: List of email messages to send
            
        Returns:
            BulkSendResult with individual results
        """
        import asyncio
        
        tasks = [self.send(message) for message in messages]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        send_results = []
        successful = 0
        failed = 0
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                send_results.append(SendResult(
                    success=False,
                    error_message=str(result),
                    provider=self.config.name
                ))
                failed += 1
            else:
                send_results.append(result)
                if result.success:
                    successful += 1
                else:
                    failed += 1
        
        return BulkSendResult(
            total=len(messages),
            successful=successful,
            failed=failed,
            results=send_results,
            provider=self.config.name
        )
    
    async def send_template(
        self,
        template_id: str,
        recipients: List[Dict[str, Any]],
        **kwargs
    ) -> BulkSendResult:
        """
        Send templated emails to multiple recipients.
        
        Args:
            template_id: The template identifier
            recipients: List of recipient data with template variables
            **kwargs: Additional provider-specific parameters
            
        Returns:
            BulkSendResult with individual results
        """
        messages = []
        
        for recipient in recipients:
            message = EmailMessage(
                to=[recipient['email']],
                subject=recipient.get('subject', ''),  # May come from template
                template_id=template_id,
                template_data=recipient.get('data', {}),
                **kwargs
            )
            messages.append(message)
        
        return await self.send_bulk(messages)
    
    async def get_message_status(self, message_id: str) -> Optional[EmailStatus]:
        """
        Get the current status of a sent message.
        
        Not all providers support this operation.
        
        Args:
            message_id: The message ID returned from send()
            
        Returns:
            Current EmailStatus or None if not found
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support message status tracking"
        )
    
    async def get_message_events(
        self,
        message_id: str,
        limit: int = 100
    ) -> List[EmailEvent]:
        """
        Get events for a specific message.
        
        Not all providers support this operation.
        
        Args:
            message_id: The message ID to get events for
            limit: Maximum number of events to return
            
        Returns:
            List of EmailEvent objects
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support event tracking"
        )
    
    async def process_webhook(self, data: Dict[str, Any]) -> List[EmailEvent]:
        """
        Process webhook data from the provider.
        
        Args:
            data: Raw webhook data from the provider
            
        Returns:
            List of EmailEvent objects
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support webhooks"
        )
    
    async def validate_domain(self, domain: str) -> bool:
        """
        Validate that a domain is properly configured for sending.
        
        Args:
            domain: The domain to validate
            
        Returns:
            True if domain is valid for sending
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support domain validation"
        )