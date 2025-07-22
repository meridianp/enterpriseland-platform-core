"""
Base classes for contact enrichment providers.
"""
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..base import BaseProvider, ProviderConfig


@dataclass
class ContactData:
    """Unified contact data model returned by all enrichment providers."""
    
    # Required fields
    email: str
    
    # Name fields
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    
    # Professional fields
    title: Optional[str] = None
    company: Optional[str] = None
    company_domain: Optional[str] = None
    department: Optional[str] = None
    seniority: Optional[str] = None
    
    # Contact fields
    phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    
    # Location fields
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    location: Optional[str] = None  # Full location string
    
    # Social profiles
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    facebook_url: Optional[str] = None
    github_url: Optional[str] = None
    
    # Additional fields
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    website: Optional[str] = None
    
    # Metadata
    confidence_score: Optional[float] = None  # 0-1 confidence in data accuracy
    last_updated: Optional[datetime] = None
    data_source: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = field(default_factory=dict)
    
    def merge_with(self, other: 'ContactData') -> 'ContactData':
        """Merge with another ContactData, preferring non-null values."""
        merged = ContactData(email=self.email)
        
        for field_name in self.__dataclass_fields__:
            if field_name == 'email':
                continue
                
            self_value = getattr(self, field_name)
            other_value = getattr(other, field_name)
            
            # Prefer non-null values, with precedence to self
            if self_value is not None:
                setattr(merged, field_name, self_value)
            elif other_value is not None:
                setattr(merged, field_name, other_value)
        
        return merged


@dataclass
class CompanyData:
    """Unified company data model returned by all enrichment providers."""
    
    # Required fields
    domain: str
    
    # Basic information
    name: Optional[str] = None
    legal_name: Optional[str] = None
    description: Optional[str] = None
    
    # Classification
    industry: Optional[str] = None
    sub_industry: Optional[str] = None
    sic_code: Optional[str] = None
    naics_code: Optional[str] = None
    tags: Optional[List[str]] = field(default_factory=list)
    
    # Size and metrics
    employee_count: Optional[int] = None
    employee_range: Optional[str] = None
    annual_revenue: Optional[float] = None
    revenue_range: Optional[str] = None
    funding_total: Optional[float] = None
    
    # Location
    headquarters_address: Optional[str] = None
    headquarters_city: Optional[str] = None
    headquarters_state: Optional[str] = None
    headquarters_country: Optional[str] = None
    
    # Contact information
    phone: Optional[str] = None
    email: Optional[str] = None
    
    # Online presence
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    facebook_url: Optional[str] = None
    crunchbase_url: Optional[str] = None
    
    # Additional information
    founded_year: Optional[int] = None
    logo_url: Optional[str] = None
    technologies: Optional[List[str]] = field(default_factory=list)
    
    # Metadata
    confidence_score: Optional[float] = None
    last_updated: Optional[datetime] = None
    data_source: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = field(default_factory=dict)


class ContactEnrichmentProvider(BaseProvider):
    """Base class for all contact enrichment providers."""
    
    @abstractmethod
    async def enrich_contact(self, email: str, **kwargs) -> ContactData:
        """
        Enrich a contact by email address.
        
        Args:
            email: The email address to enrich
            **kwargs: Additional provider-specific parameters
            
        Returns:
            ContactData with enriched information
        """
        pass
    
    @abstractmethod
    async def enrich_company(self, domain: str, **kwargs) -> CompanyData:
        """
        Enrich a company by domain.
        
        Args:
            domain: The company domain to enrich
            **kwargs: Additional provider-specific parameters
            
        Returns:
            CompanyData with enriched information
        """
        pass
    
    async def bulk_enrich_contacts(
        self, 
        emails: List[str], 
        **kwargs
    ) -> List[ContactData]:
        """
        Bulk enrich multiple contacts.
        
        Default implementation calls enrich_contact for each email.
        Providers can override for native bulk support.
        
        Args:
            emails: List of email addresses to enrich
            **kwargs: Additional provider-specific parameters
            
        Returns:
            List of ContactData objects
        """
        import asyncio
        
        tasks = [
            self.enrich_contact(email, **kwargs) 
            for email in emails
        ]
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def bulk_enrich_companies(
        self, 
        domains: List[str], 
        **kwargs
    ) -> List[CompanyData]:
        """
        Bulk enrich multiple companies.
        
        Default implementation calls enrich_company for each domain.
        Providers can override for native bulk support.
        
        Args:
            domains: List of company domains to enrich
            **kwargs: Additional provider-specific parameters
            
        Returns:
            List of CompanyData objects
        """
        import asyncio
        
        tasks = [
            self.enrich_company(domain, **kwargs) 
            for domain in domains
        ]
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def search_contacts(
        self,
        company_domain: Optional[str] = None,
        title: Optional[str] = None,
        department: Optional[str] = None,
        seniority: Optional[str] = None,
        limit: int = 10,
        **kwargs
    ) -> List[ContactData]:
        """
        Search for contacts based on criteria.
        
        Not all providers support this operation.
        
        Args:
            company_domain: Company domain to search within
            title: Job title to search for
            department: Department to filter by
            seniority: Seniority level to filter by
            limit: Maximum number of results
            **kwargs: Additional provider-specific parameters
            
        Returns:
            List of ContactData objects matching criteria
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support contact search"
        )