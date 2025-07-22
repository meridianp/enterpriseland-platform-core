"""
ComplyAdvantage Provider

Integration with ComplyAdvantage for AML screening.
"""
import requests
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from .base import (
    BaseComplianceProvider,
    KYCResult,
    AMLResult,
    DocumentVerificationResult
)


logger = logging.getLogger(__name__)


class ComplyAdvantageProvider(BaseComplianceProvider):
    """
    ComplyAdvantage provider for AML screening.
    
    ComplyAdvantage specializes in AML screening and monitoring.
    """
    
    API_BASE_URL = "https://api.complyadvantage.com"
    
    def validate_configuration(self) -> bool:
        """Validate ComplyAdvantage configuration."""
        required_fields = ['api_key']
        
        for field in required_fields:
            if not self.config.get(field):
                raise ValueError(f"ComplyAdvantage {field} not configured")
        
        return True
    
    def _make_request(
        self,
        endpoint: str,
        method: str = 'GET',
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make API request to ComplyAdvantage."""
        if not self.check_circuit_breaker():
            raise Exception("Circuit breaker is open for ComplyAdvantage")
        
        allowed, remaining = self.check_rate_limit()
        if not allowed:
            raise Exception("Rate limit exceeded for ComplyAdvantage")
        
        url = f"{self.API_BASE_URL}/{endpoint}"
        headers = {
            'Authorization': f"Bearer {self.config['api_key']}",
            'Content-Type': 'application/json'
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=data)
            else:
                response = requests.post(url, headers=headers, json=data)
            
            response.raise_for_status()
            self.record_success()
            self.increment_rate_limit()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            self.record_failure()
            logger.error(f"ComplyAdvantage API error: {e}")
            raise
    
    def verify_identity(
        self,
        first_name: str,
        last_name: str,
        date_of_birth: datetime,
        documents: List[Dict[str, Any]],
        **kwargs
    ) -> KYCResult:
        """
        ComplyAdvantage doesn't provide identity verification.
        Return a placeholder result.
        """
        return KYCResult(
            verified=False,
            risk_score=0,
            identity_verified=False,
            address_verified=False,
            documents_verified=False,
            provider_reference="N/A",
            raw_response={},
            errors=["ComplyAdvantage does not support identity verification"]
        )
    
    def verify_address(
        self,
        address_line1: str,
        city: str,
        country: str,
        documents: List[Dict[str, Any]],
        **kwargs
    ) -> KYCResult:
        """
        ComplyAdvantage doesn't provide address verification.
        Return a placeholder result.
        """
        return KYCResult(
            verified=False,
            risk_score=0,
            identity_verified=False,
            address_verified=False,
            documents_verified=False,
            provider_reference="N/A",
            raw_response={},
            errors=["ComplyAdvantage does not support address verification"]
        )
    
    def screen_individual(
        self,
        first_name: str,
        last_name: str,
        date_of_birth: Optional[datetime] = None,
        nationality: Optional[str] = None,
        **kwargs
    ) -> AMLResult:
        """Screen individual against ComplyAdvantage databases."""
        # Check cache first
        cache_key = hashlib.md5(
            f"{first_name}{last_name}{date_of_birth}".encode()
        ).hexdigest()
        
        cached_result = self.get_cached_result(f"aml_individual_{cache_key}")
        if cached_result:
            return AMLResult(**cached_result)
        
        # Build search parameters
        search_data = {
            "search_term": f"{first_name} {last_name}",
            "client_ref": kwargs.get('client_ref', cache_key),
            "search_profile": "sanctions_pep_media",
            "filters": {
                "types": ["person"],
                "birth_year": date_of_birth.year if date_of_birth else None,
                "remove_deceased": True,
                "country_codes": [nationality] if nationality else []
            }
        }
        
        try:
            # Perform search
            response = self._make_request("searches", method='POST', data=search_data)
            
            # Process results
            matches = response.get('data', {}).get('hits', [])
            result = self._process_search_results(matches, response)
            
            # Cache result
            self.cache_result(f"aml_individual_{cache_key}", result.__dict__)
            
            return result
            
        except Exception as e:
            logger.error(f"ComplyAdvantage screening error: {e}")
            return AMLResult(
                total_matches=0,
                high_risk_matches=0,
                medium_risk_matches=0,
                low_risk_matches=0,
                matches=[],
                overall_risk_score=0,
                provider_reference="",
                raw_response={"error": str(e)},
                requires_manual_review=True
            )
    
    def screen_entity(
        self,
        entity_name: str,
        entity_type: str,
        registration_country: str,
        **kwargs
    ) -> AMLResult:
        """Screen business entity against ComplyAdvantage databases."""
        # Check cache first
        cache_key = hashlib.md5(
            f"{entity_name}{registration_country}".encode()
        ).hexdigest()
        
        cached_result = self.get_cached_result(f"aml_entity_{cache_key}")
        if cached_result:
            return AMLResult(**cached_result)
        
        # Build search parameters
        search_data = {
            "search_term": entity_name,
            "client_ref": kwargs.get('client_ref', cache_key),
            "search_profile": "sanctions_pep_media",
            "filters": {
                "types": ["organisation", "company"],
                "country_codes": [registration_country],
                "entity_type": entity_type
            }
        }
        
        try:
            # Perform search
            response = self._make_request("searches", method='POST', data=search_data)
            
            # Process results
            matches = response.get('data', {}).get('hits', [])
            result = self._process_search_results(matches, response)
            
            # Cache result
            self.cache_result(f"aml_entity_{cache_key}", result.__dict__)
            
            return result
            
        except Exception as e:
            logger.error(f"ComplyAdvantage entity screening error: {e}")
            return AMLResult(
                total_matches=0,
                high_risk_matches=0,
                medium_risk_matches=0,
                low_risk_matches=0,
                matches=[],
                overall_risk_score=0,
                provider_reference="",
                raw_response={"error": str(e)},
                requires_manual_review=True
            )
    
    def verify_document(
        self,
        document_type: str,
        document_data: bytes,
        **kwargs
    ) -> DocumentVerificationResult:
        """
        ComplyAdvantage doesn't provide document verification.
        Return a placeholder result.
        """
        return DocumentVerificationResult(
            document_authentic=False,
            data_extracted={},
            confidence_score=0.0,
            tampering_detected=False,
            errors=["ComplyAdvantage does not support document verification"]
        )
    
    def _process_search_results(
        self,
        matches: List[Dict[str, Any]],
        raw_response: Dict[str, Any]
    ) -> AMLResult:
        """Process search results into AMLResult."""
        high_risk = 0
        medium_risk = 0
        low_risk = 0
        processed_matches = []
        
        for match in matches:
            match_score = match.get('match_status', 0)
            risk_level = self._determine_risk_level(match)
            
            if risk_level == 'HIGH':
                high_risk += 1
            elif risk_level == 'MEDIUM':
                medium_risk += 1
            else:
                low_risk += 1
            
            processed_matches.append({
                'match_type': self._get_match_type(match),
                'match_quality': self._get_match_quality(match_score),
                'match_score': match_score,
                'matched_name': match.get('name', ''),
                'risk_level': risk_level,
                'sources': match.get('sources', []),
                'sanctions': match.get('sanctions', []),
                'pep_roles': match.get('political_positions', []),
                'adverse_media': match.get('media', [])
            })
        
        total_matches = len(matches)
        overall_risk_score = self._calculate_overall_risk(
            high_risk, medium_risk, low_risk
        )
        
        return AMLResult(
            total_matches=total_matches,
            high_risk_matches=high_risk,
            medium_risk_matches=medium_risk,
            low_risk_matches=low_risk,
            matches=processed_matches,
            overall_risk_score=overall_risk_score,
            provider_reference=raw_response.get('id', ''),
            raw_response=raw_response,
            requires_manual_review=high_risk > 0 or overall_risk_score > 70
        )
    
    def _determine_risk_level(self, match: Dict[str, Any]) -> str:
        """Determine risk level of a match."""
        # Check for high-risk indicators
        if match.get('sanctions'):
            return 'HIGH'
        
        if match.get('political_positions'):
            # Current PEP is high risk
            for position in match['political_positions']:
                if position.get('is_current', False):
                    return 'HIGH'
            return 'MEDIUM'
        
        if match.get('media', []):
            # Adverse media indicates medium risk
            return 'MEDIUM'
        
        return 'LOW'
    
    def _get_match_type(self, match: Dict[str, Any]) -> str:
        """Determine the type of match."""
        if match.get('sanctions'):
            return 'SANCTIONS'
        elif match.get('political_positions'):
            return 'PEP'
        elif match.get('media'):
            return 'ADVERSE_MEDIA'
        else:
            return 'OTHER'
    
    def _get_match_quality(self, match_score: int) -> str:
        """Determine match quality based on score."""
        if match_score >= 90:
            return 'EXACT'
        elif match_score >= 80:
            return 'STRONG'
        elif match_score >= 60:
            return 'POSSIBLE'
        else:
            return 'WEAK'
    
    def _calculate_overall_risk(
        self,
        high_risk: int,
        medium_risk: int,
        low_risk: int
    ) -> int:
        """Calculate overall risk score."""
        if high_risk > 0:
            return min(100, 70 + (high_risk * 10))
        elif medium_risk > 0:
            return min(70, 40 + (medium_risk * 10))
        elif low_risk > 0:
            return min(40, 10 + (low_risk * 5))
        else:
            return 0
    
    def get_screening_report(self, search_id: str) -> Dict[str, Any]:
        """Get detailed screening report for a search."""
        try:
            response = self._make_request(f"searches/{search_id}")
            return response
        except Exception as e:
            logger.error(f"Failed to get screening report: {e}")
            return {}
    
    def add_to_monitoring(
        self,
        search_id: str,
        monitoring_config: Dict[str, Any]
    ) -> bool:
        """Add entity to ongoing monitoring."""
        try:
            data = {
                "search_id": search_id,
                "is_monitored": True,
                "monitoring_config": monitoring_config
            }
            
            response = self._make_request(
                f"searches/{search_id}/monitoring",
                method='POST',
                data=data
            )
            
            return response.get('data', {}).get('is_monitored', False)
            
        except Exception as e:
            logger.error(f"Failed to add to monitoring: {e}")
            return False