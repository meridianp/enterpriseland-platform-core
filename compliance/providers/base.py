"""
Base Compliance Provider

Abstract base class for compliance service providers.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
import logging

from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)


@dataclass
class KYCResult:
    """Result of KYC verification."""
    verified: bool
    risk_score: int
    identity_verified: bool
    address_verified: bool
    documents_verified: bool
    provider_reference: str
    raw_response: Dict[str, Any]
    errors: List[str] = None
    warnings: List[str] = None
    
    
@dataclass
class AMLResult:
    """Result of AML screening."""
    total_matches: int
    high_risk_matches: int
    medium_risk_matches: int
    low_risk_matches: int
    matches: List[Dict[str, Any]]
    overall_risk_score: int
    provider_reference: str
    raw_response: Dict[str, Any]
    requires_manual_review: bool = False
    

@dataclass
class DocumentVerificationResult:
    """Result of document verification."""
    document_authentic: bool
    data_extracted: Dict[str, Any]
    confidence_score: float
    tampering_detected: bool
    expiry_date: Optional[datetime] = None
    errors: List[str] = None


class BaseComplianceProvider(ABC):
    """
    Abstract base class for compliance providers.
    
    All compliance providers must implement these methods.
    """
    
    def __init__(self):
        self.provider_name = self.__class__.__name__.replace('Provider', '').lower()
        self.config = self._load_configuration()
        self.circuit_breaker_key = f"compliance_circuit_{self.provider_name}"
        self.rate_limit_key = f"compliance_rate_{self.provider_name}"
    
    def _load_configuration(self) -> Dict[str, Any]:
        """Load provider-specific configuration."""
        config_key = f"COMPLIANCE_PROVIDERS_{self.provider_name.upper()}"
        return getattr(settings, config_key, {})
    
    @abstractmethod
    def validate_configuration(self) -> bool:
        """
        Validate provider configuration.
        
        Returns:
            True if configuration is valid
            
        Raises:
            ValueError: If configuration is invalid
        """
        pass
    
    @abstractmethod
    def verify_identity(
        self,
        first_name: str,
        last_name: str,
        date_of_birth: datetime,
        documents: List[Dict[str, Any]],
        **kwargs
    ) -> KYCResult:
        """
        Perform identity verification.
        
        Args:
            first_name: Person's first name
            last_name: Person's last name
            date_of_birth: Date of birth
            documents: List of document data
            **kwargs: Additional provider-specific parameters
            
        Returns:
            KYCResult object
        """
        pass
    
    @abstractmethod
    def verify_address(
        self,
        address_line1: str,
        city: str,
        country: str,
        documents: List[Dict[str, Any]],
        **kwargs
    ) -> KYCResult:
        """
        Perform address verification.
        
        Args:
            address_line1: Primary address line
            city: City name
            country: Country code (ISO)
            documents: List of address proof documents
            **kwargs: Additional parameters
            
        Returns:
            KYCResult object
        """
        pass
    
    @abstractmethod
    def screen_individual(
        self,
        first_name: str,
        last_name: str,
        date_of_birth: Optional[datetime] = None,
        nationality: Optional[str] = None,
        **kwargs
    ) -> AMLResult:
        """
        Screen individual against AML databases.
        
        Args:
            first_name: Person's first name
            last_name: Person's last name
            date_of_birth: Date of birth
            nationality: Nationality (ISO country code)
            **kwargs: Additional parameters
            
        Returns:
            AMLResult object
        """
        pass
    
    @abstractmethod
    def screen_entity(
        self,
        entity_name: str,
        entity_type: str,
        registration_country: str,
        **kwargs
    ) -> AMLResult:
        """
        Screen business entity against AML databases.
        
        Args:
            entity_name: Business name
            entity_type: Type of entity
            registration_country: Country of registration
            **kwargs: Additional parameters
            
        Returns:
            AMLResult object
        """
        pass
    
    @abstractmethod
    def verify_document(
        self,
        document_type: str,
        document_data: bytes,
        **kwargs
    ) -> DocumentVerificationResult:
        """
        Verify a document's authenticity.
        
        Args:
            document_type: Type of document
            document_data: Document file data
            **kwargs: Additional parameters
            
        Returns:
            DocumentVerificationResult object
        """
        pass
    
    def check_circuit_breaker(self) -> bool:
        """
        Check if circuit breaker is open.
        
        Returns:
            True if service is available, False if circuit is open
        """
        failures = cache.get(self.circuit_breaker_key, 0)
        return failures < 5  # Allow 5 failures before opening circuit
    
    def record_failure(self):
        """Record a service failure for circuit breaker."""
        failures = cache.get(self.circuit_breaker_key, 0)
        cache.set(self.circuit_breaker_key, failures + 1, timeout=300)  # 5 min window
        
        if failures + 1 >= 5:
            logger.error(f"Circuit breaker opened for {self.provider_name}")
    
    def record_success(self):
        """Record a successful call to reset circuit breaker."""
        cache.delete(self.circuit_breaker_key)
    
    def check_rate_limit(self) -> Tuple[bool, int]:
        """
        Check rate limiting.
        
        Returns:
            Tuple of (is_allowed, remaining_calls)
        """
        current_count = cache.get(self.rate_limit_key, 0)
        limit = self.config.get('rate_limit', 100)
        
        if current_count >= limit:
            return False, 0
        
        return True, limit - current_count
    
    def increment_rate_limit(self):
        """Increment rate limit counter."""
        current = cache.get(self.rate_limit_key, 0)
        cache.set(self.rate_limit_key, current + 1, timeout=3600)  # 1 hour window
    
    def get_webhook_url(self) -> str:
        """Get webhook URL for this provider."""
        base_url = settings.COMPLIANCE_WEBHOOK_BASE_URL
        return f"{base_url}/compliance/webhooks/{self.provider_name}/"
    
    def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle webhook from provider.
        
        Args:
            payload: Webhook payload
            
        Returns:
            Processing result
        """
        # Default implementation - providers can override
        logger.info(f"Received webhook for {self.provider_name}: {payload}")
        return {"status": "processed"}
    
    def get_cached_result(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached verification result."""
        return cache.get(f"compliance_{self.provider_name}_{cache_key}")
    
    def cache_result(self, cache_key: str, result: Dict[str, Any], timeout: int = 86400):
        """Cache verification result."""
        cache.set(f"compliance_{self.provider_name}_{cache_key}", result, timeout=timeout)