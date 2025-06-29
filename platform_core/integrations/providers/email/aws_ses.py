"""
AWS SES email provider implementation.

Provides integration with Amazon Simple Email Service (SES) for sending
high-volume transactional and marketing emails with bounce/complaint handling.
"""
import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import base64

import boto3
from botocore.exceptions import ClientError, BotoCoreError

from ..base import ProviderConfig
from .base import (
    EmailProvider, EmailMessage, SendResult, BulkSendResult,
    EmailStatus, EmailEvent, EmailAttachment
)

logger = logging.getLogger(__name__)


class AWSSESProvider(EmailProvider):
    """AWS SES email provider implementation."""
    
    def __init__(self, config: ProviderConfig):
        """Initialize AWS SES provider."""
        super().__init__(config)
        
        # AWS configuration
        self.aws_access_key_id = config.params.get('aws_access_key_id')
        self.aws_secret_access_key = config.params.get('aws_secret_access_key')
        self.aws_region = config.params.get('aws_region', 'us-east-1')
        self.configuration_set = config.params.get('configuration_set')
        
        # Default sender
        self.from_email = config.params.get('from_email', 'noreply@example.com')
        self.from_name = config.params.get('from_name', 'EnterpriseLand')
        
        # Initialize SES client
        self.client = boto3.client(
            'ses',
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key
        )
        
        # Initialize SNS client for bounce/complaint notifications
        self.sns_client = boto3.client(
            'sns',
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key
        )
    
    async def execute(self, **kwargs):
        """Execute email sending operation."""
        if 'messages' in kwargs:
            return await self.send_bulk(kwargs['messages'])
        else:
            message = EmailMessage(**kwargs)
            return await self.send(message)
    
    async def send(self, message: EmailMessage) -> SendResult:
        """Send a single email message using AWS SES."""
        # Validate message
        message.validate()
        
        try:
            # Build SES message
            ses_message = self._build_ses_message(message)
            
            # Add configuration set if available
            if self.configuration_set:
                ses_message['ConfigurationSetName'] = self.configuration_set
            
            # Send email
            response = self.client.send_email(**ses_message)
            
            return SendResult(
                success=True,
                message_id=response['MessageId'],
                provider="aws_ses",
                metadata={
                    "request_id": response.get('ResponseMetadata', {}).get('RequestId'),
                    "http_status_code": response.get('ResponseMetadata', {}).get('HTTPStatusCode')
                }
            )
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            logger.error(f"AWS SES error: {error_code} - {error_message}")
            
            return SendResult(
                success=False,
                error_code=error_code,
                error_message=error_message,
                provider="aws_ses"
            )
        except Exception as e:
            logger.error(f"AWS SES provider error: {str(e)}")
            return SendResult(
                success=False,
                error_code="PROVIDER_ERROR",
                error_message=str(e),
                provider="aws_ses"
            )
    
    async def send_bulk(self, messages: List[EmailMessage]) -> BulkSendResult:
        """
        Send multiple emails using AWS SES.
        
        SES supports bulk sending through send_bulk_templated_email,
        but for flexibility we'll send individually with rate limiting.
        """
        if not messages:
            return BulkSendResult(
                total=0,
                successful=0,
                failed=0,
                results=[],
                provider="aws_ses"
            )
        
        results = []
        successful = 0
        failed = 0
        
        # Get current send rate
        try:
            quota = self.client.get_send_quota()
            max_send_rate = quota.get('MaxSendRate', 1)
        except:
            max_send_rate = 1  # Default to 1 per second
        
        import asyncio
        
        for i, message in enumerate(messages):
            # Rate limiting
            if i > 0:
                await asyncio.sleep(1.0 / max_send_rate)
            
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
            provider="aws_ses"
        )
    
    async def send_raw_email(self, message: EmailMessage) -> SendResult:
        """
        Send email using raw format (for complex messages with attachments).
        """
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email.mime.application import MIMEApplication
            from email import encoders
            from email.utils import formataddr
            
            # Create MIME message
            msg = MIMEMultipart('mixed')
            msg['Subject'] = message.subject
            msg['From'] = formataddr((
                message.from_name or self.from_name,
                message.from_email or self.from_email
            ))
            msg['To'] = ', '.join(message.to)
            
            if message.cc:
                msg['Cc'] = ', '.join(message.cc)
            
            if message.reply_to:
                msg['Reply-To'] = message.reply_to
            
            # Add custom headers
            if message.headers:
                for key, value in message.headers.items():
                    msg[key] = value
            
            # Create body part
            msg_body = MIMEMultipart('alternative')
            
            # Add text content
            if message.text_content:
                text_part = MIMEText(message.text_content, 'plain', 'utf-8')
                msg_body.attach(text_part)
            
            # Add HTML content
            if message.html_content:
                html_part = MIMEText(message.html_content, 'html', 'utf-8')
                msg_body.attach(html_part)
            
            msg.attach(msg_body)
            
            # Add attachments
            if message.attachments:
                for attachment in message.attachments:
                    # Create attachment
                    part = MIMEApplication(attachment.content)
                    part.add_header(
                        'Content-Disposition',
                        attachment.disposition,
                        filename=attachment.filename
                    )
                    
                    if attachment.content_id:
                        part.add_header('Content-ID', f'<{attachment.content_id}>')
                    
                    msg.attach(part)
            
            # Build destination
            destinations = {
                'ToAddresses': message.to,
                'CcAddresses': message.cc or [],
                'BccAddresses': message.bcc or []
            }
            
            # Send raw email
            response = self.client.send_raw_email(
                Source=msg['From'],
                Destinations=message.to + (message.cc or []) + (message.bcc or []),
                RawMessage={'Data': msg.as_string()},
                ConfigurationSetName=self.configuration_set if self.configuration_set else None
            )
            
            return SendResult(
                success=True,
                message_id=response['MessageId'],
                provider="aws_ses",
                metadata={
                    "request_id": response.get('ResponseMetadata', {}).get('RequestId')
                }
            )
            
        except Exception as e:
            logger.error(f"AWS SES raw email error: {str(e)}")
            return SendResult(
                success=False,
                error_code="RAW_EMAIL_ERROR",
                error_message=str(e),
                provider="aws_ses"
            )
    
    async def process_webhook(self, data: Dict[str, Any]) -> List[EmailEvent]:
        """
        Process SNS notifications from AWS SES.
        
        SES sends notifications via SNS for bounces, complaints, and deliveries.
        """
        events = []
        
        try:
            # Handle SNS notification structure
            if 'Message' in data:
                # Parse SNS message
                message_data = json.loads(data['Message'])
            else:
                message_data = data
            
            notification_type = message_data.get('notificationType', '').lower()
            
            # Map SES notification types to our EmailStatus
            type_map = {
                'bounce': EmailStatus.BOUNCED,
                'complaint': EmailStatus.SPAM,
                'delivery': EmailStatus.DELIVERED,
                'send': EmailStatus.SENT,
                'reject': EmailStatus.FAILED,
                'open': EmailStatus.OPENED,
                'click': EmailStatus.CLICKED,
                'rendering_failure': EmailStatus.FAILED
            }
            
            if notification_type in type_map:
                mail = message_data.get('mail', {})
                message_id = mail.get('messageId')
                
                if message_id:
                    # Get timestamp
                    timestamp_str = (
                        message_data.get('bounce', {}).get('timestamp') or
                        message_data.get('complaint', {}).get('timestamp') or
                        message_data.get('delivery', {}).get('timestamp') or
                        message_data.get('send', {}).get('timestamp') or
                        message_data.get('open', {}).get('timestamp') or
                        message_data.get('click', {}).get('timestamp') or
                        message_data.get('mail', {}).get('timestamp')
                    )
                    
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    else:
                        timestamp = datetime.now()
                    
                    # Extract recipients
                    recipients = []
                    if notification_type == 'bounce':
                        recipients = [
                            r.get('emailAddress') 
                            for r in message_data.get('bounce', {}).get('bouncedRecipients', [])
                        ]
                    elif notification_type == 'complaint':
                        recipients = [
                            r.get('emailAddress') 
                            for r in message_data.get('complaint', {}).get('complainedRecipients', [])
                        ]
                    else:
                        recipients = mail.get('destination', [])
                    
                    # Create event for each recipient
                    for recipient in recipients:
                        event = EmailEvent(
                            message_id=message_id,
                            event_type=type_map[notification_type],
                            timestamp=timestamp,
                            recipient=recipient,
                            reason=self._extract_reason(notification_type, message_data),
                            provider="aws_ses",
                            raw_data=message_data
                        )
                        
                        # Add specific data for clicks
                        if notification_type == 'click':
                            event.url = message_data.get('click', {}).get('link')
                            event.ip_address = message_data.get('click', {}).get('ipAddress')
                            event.user_agent = message_data.get('click', {}).get('userAgent')
                        
                        events.append(event)
        
        except Exception as e:
            logger.error(f"Error processing AWS SES webhook: {str(e)}")
        
        return events
    
    async def validate_domain(self, domain: str) -> bool:
        """
        Check if a domain is verified with AWS SES.
        """
        try:
            # Get verified domains
            response = self.client.list_verified_email_addresses()
            verified_addresses = response.get('VerifiedEmailAddresses', [])
            
            # Check if any address from this domain is verified
            for address in verified_addresses:
                if address.endswith(f'@{domain}'):
                    return True
            
            # Also check domain verification
            domain_response = self.client.get_identity_verification_attributes(
                Identities=[domain]
            )
            
            attributes = domain_response.get('VerificationAttributes', {})
            domain_attr = attributes.get(domain, {})
            
            return domain_attr.get('VerificationStatus') == 'Success'
            
        except Exception as e:
            logger.error(f"Error validating domain with AWS SES: {str(e)}")
            return False
    
    async def get_send_statistics(self) -> Dict[str, Any]:
        """Get sending statistics from AWS SES."""
        try:
            # Get send quota
            quota = self.client.get_send_quota()
            
            # Get send statistics
            stats = self.client.get_send_statistics()
            
            return {
                "quota": {
                    "max_24_hour_send": quota.get('Max24HourSend'),
                    "sent_last_24_hours": quota.get('SentLast24Hours'),
                    "max_send_rate": quota.get('MaxSendRate')
                },
                "statistics": stats.get('SendDataPoints', [])
            }
            
        except Exception as e:
            logger.error(f"Error getting SES statistics: {str(e)}")
            return {}
    
    async def health_check(self) -> bool:
        """Check if AWS SES is accessible."""
        try:
            # Try to get send quota as a health check
            self.client.get_send_quota()
            return True
        except Exception as e:
            logger.error(f"AWS SES health check failed: {str(e)}")
            return False
    
    def _build_ses_message(self, message: EmailMessage) -> Dict[str, Any]:
        """Build SES message structure from EmailMessage."""
        # Use raw email for complex messages
        if message.attachments or message.template_id:
            # For now, use simple format
            # TODO: Implement raw email format for attachments
            pass
        
        ses_message = {
            'Source': f"{message.from_name or self.from_name} <{message.from_email or self.from_email}>",
            'Destination': {
                'ToAddresses': message.to,
                'CcAddresses': message.cc or [],
                'BccAddresses': message.bcc or []
            },
            'Message': {
                'Subject': {
                    'Data': message.subject,
                    'Charset': 'UTF-8'
                },
                'Body': {}
            }
        }
        
        # Add reply-to
        if message.reply_to:
            ses_message['ReplyToAddresses'] = [message.reply_to]
        
        # Add body content
        if message.text_content:
            ses_message['Message']['Body']['Text'] = {
                'Data': message.text_content,
                'Charset': 'UTF-8'
            }
        
        if message.html_content:
            ses_message['Message']['Body']['Html'] = {
                'Data': message.html_content,
                'Charset': 'UTF-8'
            }
        
        # Add tags (SES supports up to 10 tags)
        if message.tags:
            ses_message['Tags'] = [
                {'Name': tag, 'Value': 'true'} 
                for tag in message.tags[:10]
            ]
        
        return ses_message
    
    def _extract_reason(self, notification_type: str, data: Dict[str, Any]) -> Optional[str]:
        """Extract reason from SES notification data."""
        if notification_type == 'bounce':
            bounce = data.get('bounce', {})
            bounce_type = bounce.get('bounceType')
            bounce_subtype = bounce.get('bounceSubType')
            return f"{bounce_type}: {bounce_subtype}" if bounce_type else None
        
        elif notification_type == 'complaint':
            complaint = data.get('complaint', {})
            feedback_type = complaint.get('complaintFeedbackType')
            return f"Complaint: {feedback_type}" if feedback_type else "Spam complaint"
        
        elif notification_type == 'reject':
            return data.get('reject', {}).get('reason')
        
        elif notification_type == 'rendering_failure':
            return data.get('failure', {}).get('errorMessage')
        
        return None