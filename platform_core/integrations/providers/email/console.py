"""
Console email provider for development.
"""
import logging
from typing import List, Optional, Dict, Any

from ..base import ProviderConfig
from .base import EmailProvider, EmailMessage, SendResult as EmailResult


logger = logging.getLogger(__name__)


class ConsoleEmailProvider(EmailProvider):
    """Console email provider that logs emails instead of sending them."""
    
    def __init__(self, config: ProviderConfig):
        """Initialize console provider."""
        super().__init__(config)
    
    async def execute(self, **kwargs):
        """Execute email sending operation."""
        # Delegate to the appropriate method
        if 'messages' in kwargs:
            return await self.send_bulk(kwargs['messages'])
        else:
            return await self.send(EmailMessage(**kwargs))
    
    async def send(self, message: EmailMessage) -> EmailResult:
        """Log email to console instead of sending."""
        # Validate message
        message.validate()
        
        logger.info("=" * 80)
        logger.info("EMAIL MESSAGE")
        logger.info("=" * 80)
        logger.info(f"From: {message.from_email or 'noreply@example.com'}")
        logger.info(f"To: {', '.join(message.to)}")
        logger.info(f"Subject: {message.subject}")
        logger.info("-" * 80)
        if message.text_content:
            logger.info("Text Content:")
            logger.info(message.text_content)
            logger.info("-" * 80)
        logger.info("HTML Content:")
        logger.info(message.html_content or '(No HTML content)')
        logger.info("=" * 80)
        
        return EmailResult(
            success=True,
            message_id=f"console-{hash(message.subject)}-{hash(message.to[0])}",
            provider="console",
            metadata={"logged": True}
        )
    
    async def get_email_status(self, message_id: str) -> Dict[str, Any]:
        """Get status of a logged email."""
        return {
            "message_id": message_id,
            "status": "logged",
            "provider": "console"
        }
    
    async def health_check(self) -> bool:
        """Console provider is always healthy."""
        return True