"""
Mock providers and utilities for testing the provider abstraction layer.
"""
import random
import string
from typing import List, Dict, Any
from datetime import datetime

from .providers.base import ProviderConfig
from .providers.enrichment.base import ContactEnrichmentProvider, ContactData, CompanyData
from .providers.email.base import EmailProvider, EmailMessage, SendResult, BulkSendResult, EmailStatus


class MockEnrichmentProvider(ContactEnrichmentProvider):
    """Mock enrichment provider for testing."""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.fail_rate = config.params.get('fail_rate', 0.0) if hasattr(config, 'params') else 0.0
        self.response_data = config.params.get('response_data', {}) if hasattr(config, 'params') else {}
    
    async def execute(self, **kwargs):
        """Execute enrichment operation."""
        # Determine operation type and delegate
        if 'email' in kwargs:
            return await self.enrich_contact(kwargs['email'])
        elif 'domain' in kwargs:
            return await self.enrich_company(kwargs['domain'])
        else:
            raise ValueError("Either 'email' or 'domain' must be provided")
    
    async def enrich_contact(self, email: str, **kwargs) -> ContactData:
        """Mock contact enrichment."""
        # Simulate random failures
        if random.random() < self.fail_rate:
            raise Exception("Mock provider failure")
        
        # Generate mock data
        username = email.split('@')[0]
        domain = email.split('@')[1]
        
        return ContactData(
            email=email,
            first_name=self.response_data.get('first_name', username.split('.')[0].title()),
            last_name=self.response_data.get('last_name', username.split('.')[-1].title() if '.' in username else 'User'),
            full_name=self.response_data.get('full_name', username.replace('.', ' ').title()),
            title=self.response_data.get('title', 'Software Engineer'),
            company=self.response_data.get('company', domain.split('.')[0].title()),
            company_domain=domain,
            phone=self.response_data.get('phone', '+1-555-0123'),
            location=self.response_data.get('location', 'San Francisco, CA'),
            linkedin_url=f"https://linkedin.com/in/{username}",
            confidence_score=0.95,
            last_updated=datetime.now(),
            data_source='mock'
        )
    
    async def enrich_company(self, domain: str, **kwargs) -> CompanyData:
        """Mock company enrichment."""
        # Simulate random failures
        if random.random() < self.fail_rate:
            raise Exception("Mock provider failure")
        
        company_name = domain.split('.')[0].title()
        
        return CompanyData(
            domain=domain,
            name=self.response_data.get('name', company_name),
            description=self.response_data.get('description', f"{company_name} is a leading technology company."),
            industry=self.response_data.get('industry', 'Technology'),
            employee_count=self.response_data.get('employee_count', 500),
            employee_range=self.response_data.get('employee_range', '100-500'),
            founded_year=self.response_data.get('founded_year', 2010),
            headquarters_city=self.response_data.get('headquarters_city', 'San Francisco'),
            headquarters_state=self.response_data.get('headquarters_state', 'CA'),
            headquarters_country=self.response_data.get('headquarters_country', 'USA'),
            website=f"https://{domain}",
            linkedin_url=f"https://linkedin.com/company/{company_name.lower()}",
            technologies=['Python', 'Django', 'PostgreSQL', 'React'],
            confidence_score=0.92,
            last_updated=datetime.now(),
            data_source='mock'
        )
    
    async def health_check(self) -> bool:
        """Mock health check."""
        return self.fail_rate < 0.5


class MockEmailProvider(EmailProvider):
    """Mock email provider for testing."""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.fail_rate = config.params.get('fail_rate', 0.0) if hasattr(config, 'params') else 0.0
        self.sent_messages: List[EmailMessage] = []
    
    async def execute(self, **kwargs):
        """Execute email sending operation."""
        # Delegate to the appropriate method
        if 'messages' in kwargs:
            return await self.send_bulk(kwargs['messages'])
        else:
            return await self.send(EmailMessage(**kwargs))
    
    async def send(self, message: EmailMessage) -> SendResult:
        """Mock email sending."""
        import time
        start_time = time.time()
        
        # Validate message
        message.validate()
        
        # Simulate random failures
        if random.random() < self.fail_rate:
            return SendResult(
                success=False,
                error_code='MOCK_ERROR',
                error_message='Mock provider failure',
                provider='mock'
            )
        
        # Generate mock message ID
        message_id = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        
        # Store the message
        self.sent_messages.append(message)
        
        # Record metrics
        duration = time.time() - start_time
        self._record_request(duration, success=True)
        
        return SendResult(
            success=True,
            message_id=message_id,
            provider='mock',
            metadata={
                'duration': duration,
                'test': True
            }
        )
    
    async def send_bulk(self, messages: List[EmailMessage]) -> BulkSendResult:
        """Mock bulk email sending."""
        results = []
        for message in messages:
            result = await self.send(message)
            results.append(result)
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        return BulkSendResult(
            total=len(messages),
            successful=successful,
            failed=failed,
            results=results,
            provider='mock'
        )
    
    async def get_message_status(self, message_id: str) -> EmailStatus:
        """Mock message status."""
        # Simulate different statuses
        statuses = [
            EmailStatus.DELIVERED,
            EmailStatus.OPENED,
            EmailStatus.CLICKED
        ]
        return random.choice(statuses)
    
    async def health_check(self) -> bool:
        """Mock health check."""
        return self.fail_rate < 0.5
    
    def get_sent_messages(self) -> List[EmailMessage]:
        """Get all sent messages for testing."""
        return self.sent_messages.copy()
    
    def clear_sent_messages(self):
        """Clear sent messages for testing."""
        self.sent_messages.clear()


def get_test_provider_config() -> Dict[str, Any]:
    """Get test configuration for providers."""
    return {
        'contact_enrichment': {
            'default': 'mock',
            'fallback_order': ['mock', 'mock2'],
            'providers': {
                'mock': {
                    'class': 'integrations.testing.MockEnrichmentProvider',
                    'enabled': True,
                    'params': {
                        'fail_rate': 0.0
                    },
                    'timeout': 5,
                    'cache_ttl': 60
                },
                'mock2': {
                    'class': 'integrations.testing.MockEnrichmentProvider',
                    'enabled': True,
                    'params': {
                        'fail_rate': 0.2,
                        'response_data': {
                            'title': 'Senior Engineer',
                            'company': 'Mock Corp'
                        }
                    },
                    'timeout': 5,
                    'cache_ttl': 60
                }
            }
        },
        'email': {
            'default': 'mock',
            'providers': {
                'mock': {
                    'class': 'integrations.testing.MockEmailProvider',
                    'enabled': True,
                    'params': {
                        'fail_rate': 0.0
                    },
                    'timeout': 10
                }
            }
        }
    }