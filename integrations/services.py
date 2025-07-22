"""
High-level service interfaces for provider operations.
"""
import logging
from typing import Optional, List, Dict, Any
from django.utils import timezone

from .registry import provider_registry
from .providers.enrichment.base import ContactData, CompanyData
from .providers.email.base import EmailMessage, SendResult, BulkSendResult

logger = logging.getLogger(__name__)


class EnrichmentService:
    """
    High-level service for contact and company enrichment.
    
    Provides a simple interface for enrichment operations with
    automatic provider fallback and caching.
    """
    
    async def enrich_contact(
        self,
        email: str,
        providers: Optional[List[str]] = None,
        merge_results: bool = False,
        **kwargs
    ) -> ContactData:
        """
        Enrich a contact by email address.
        
        Args:
            email: Email address to enrich
            providers: Optional list of providers to use (in order)
            merge_results: If True, try multiple providers and merge results
            **kwargs: Additional provider-specific parameters
            
        Returns:
            ContactData with enriched information
        """
        if merge_results and not providers:
            # Get all available providers for merging
            providers = provider_registry.get_available_providers('contact_enrichment')
        
        if merge_results:
            # Try multiple providers and merge results
            merged_data = ContactData(email=email)
            errors = []
            
            for provider in providers:
                try:
                    result = await provider_registry.execute(
                        service='contact_enrichment',
                        operation='enrich_contact',
                        providers=[provider],
                        email=email,
                        **kwargs
                    )
                    merged_data = merged_data.merge_with(result)
                except Exception as e:
                    errors.append(f"{provider}: {str(e)}")
                    logger.warning(f"Provider {provider} failed during merge: {e}")
            
            if not merged_data.first_name and not merged_data.last_name:
                # No data was enriched
                logger.error(f"All providers failed to enrich {email}: {errors}")
            
            return merged_data
        else:
            # Use single provider with fallback
            return await provider_registry.execute(
                service='contact_enrichment',
                operation='enrich_contact',
                providers=providers,
                email=email,
                **kwargs
            )
    
    async def enrich_company(
        self,
        domain: str,
        providers: Optional[List[str]] = None,
        **kwargs
    ) -> CompanyData:
        """
        Enrich a company by domain.
        
        Args:
            domain: Company domain to enrich
            providers: Optional list of providers to use (in order)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            CompanyData with enriched information
        """
        return await provider_registry.execute(
            service='contact_enrichment',
            operation='enrich_company',
            providers=providers,
            domain=domain,
            **kwargs
        )
    
    async def bulk_enrich_contacts(
        self,
        emails: List[str],
        providers: Optional[List[str]] = None,
        batch_size: int = 100,
        **kwargs
    ) -> List[ContactData]:
        """
        Bulk enrich multiple contacts.
        
        Args:
            emails: List of email addresses to enrich
            providers: Optional list of providers to use
            batch_size: Batch size for processing
            **kwargs: Additional provider-specific parameters
            
        Returns:
            List of ContactData objects
        """
        results = []
        
        # Process in batches
        for i in range(0, len(emails), batch_size):
            batch = emails[i:i + batch_size]
            
            batch_results = await provider_registry.execute(
                service='contact_enrichment',
                operation='bulk_enrich_contacts',
                providers=providers,
                emails=batch,
                **kwargs
            )
            
            results.extend(batch_results)
        
        return results
    
    async def search_contacts(
        self,
        company_domain: Optional[str] = None,
        title: Optional[str] = None,
        department: Optional[str] = None,
        seniority: Optional[str] = None,
        limit: int = 10,
        providers: Optional[List[str]] = None,
        **kwargs
    ) -> List[ContactData]:
        """
        Search for contacts based on criteria.
        
        Args:
            company_domain: Company domain to search within
            title: Job title to search for
            department: Department to filter by
            seniority: Seniority level to filter by
            limit: Maximum number of results
            providers: Optional list of providers to use
            **kwargs: Additional provider-specific parameters
            
        Returns:
            List of ContactData objects matching criteria
        """
        return await provider_registry.execute(
            service='contact_enrichment',
            operation='search_contacts',
            providers=providers,
            company_domain=company_domain,
            title=title,
            department=department,
            seniority=seniority,
            limit=limit,
            **kwargs
        )


class EmailService:
    """
    High-level service for sending emails.
    
    Provides a simple interface for email operations with
    automatic provider fallback and delivery tracking.
    """
    
    async def send_email(
        self,
        to: List[str],
        subject: str,
        html_content: Optional[str] = None,
        text_content: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs
    ) -> SendResult:
        """
        Send an email message.
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            html_content: HTML content of the email
            text_content: Plain text content of the email
            from_email: Sender email address
            from_name: Sender name
            provider: Optional specific provider to use
            **kwargs: Additional message parameters
            
        Returns:
            SendResult indicating success/failure
        """
        message = EmailMessage(
            to=to,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            from_email=from_email,
            from_name=from_name,
            **kwargs
        )
        
        providers = [provider] if provider else None
        
        result = await provider_registry.execute(
            service='email',
            operation='send',
            providers=providers,
            message=message
        )
        
        # Log the result
        self._log_email_result(message, result)
        
        return result
    
    async def send_template_email(
        self,
        template_id: str,
        to: List[str],
        template_data: Dict[str, Any],
        subject: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs
    ) -> SendResult:
        """
        Send a templated email.
        
        Args:
            template_id: Template identifier
            to: List of recipient email addresses
            template_data: Data to populate the template
            subject: Optional subject (may come from template)
            from_email: Sender email address
            from_name: Sender name
            provider: Optional specific provider to use
            **kwargs: Additional message parameters
            
        Returns:
            SendResult indicating success/failure
        """
        message = EmailMessage(
            to=to,
            subject=subject or '',
            template_id=template_id,
            template_data=template_data,
            from_email=from_email,
            from_name=from_name,
            **kwargs
        )
        
        providers = [provider] if provider else None
        
        return await provider_registry.execute(
            service='email',
            operation='send',
            providers=providers,
            message=message
        )
    
    async def send_bulk_emails(
        self,
        messages: List[EmailMessage],
        provider: Optional[str] = None,
        batch_size: int = 1000
    ) -> BulkSendResult:
        """
        Send multiple emails in bulk.
        
        Args:
            messages: List of email messages to send
            provider: Optional specific provider to use
            batch_size: Batch size for processing
            
        Returns:
            BulkSendResult with individual results
        """
        all_results = []
        total_successful = 0
        total_failed = 0
        
        # Process in batches
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            
            providers = [provider] if provider else None
            
            result = await provider_registry.execute(
                service='email',
                operation='send_bulk',
                providers=providers,
                messages=batch
            )
            
            all_results.extend(result.results)
            total_successful += result.successful
            total_failed += result.failed
        
        return BulkSendResult(
            total=len(messages),
            successful=total_successful,
            failed=total_failed,
            results=all_results,
            provider=provider
        )
    
    async def send_campaign(
        self,
        campaign_id: str,
        template_id: str,
        recipients: List[Dict[str, Any]],
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs
    ) -> BulkSendResult:
        """
        Send a campaign to multiple recipients.
        
        Args:
            campaign_id: Campaign identifier for tracking
            template_id: Template to use
            recipients: List of recipient data with email and template variables
            from_email: Sender email address
            from_name: Sender name
            provider: Optional specific provider to use
            **kwargs: Additional campaign parameters
            
        Returns:
            BulkSendResult with individual results
        """
        messages = []
        
        for recipient in recipients:
            message = EmailMessage(
                to=[recipient['email']],
                subject=recipient.get('subject', ''),
                template_id=template_id,
                template_data=recipient.get('data', {}),
                from_email=from_email,
                from_name=from_name,
                campaign_id=campaign_id,
                metadata={
                    'recipient_id': recipient.get('id'),
                    'campaign_id': campaign_id
                },
                **kwargs
            )
            messages.append(message)
        
        return await self.send_bulk_emails(messages, provider=provider)
    
    def _log_email_result(self, message: EmailMessage, result: SendResult):
        """Log email send result for tracking."""
        # This would integrate with your email logging system
        # For now, just log to standard logger
        if result.success:
            logger.info(
                f"Email sent successfully to {message.to} "
                f"via {result.provider} (ID: {result.message_id})"
            )
        else:
            logger.error(
                f"Failed to send email to {message.to}: "
                f"{result.error_message} (Code: {result.error_code})"
            )


# Service instances
enrichment_service = EnrichmentService()
email_service = EmailService()