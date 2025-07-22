"""
KYC Service

Service layer for KYC verification operations.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from django.db import transaction
from django.utils import timezone
from celery import shared_task

from ..models import (
    KYCVerification,
    KYCDocument,
    IdentityDocument,
    AddressProof,
    BusinessVerification
)
from ..providers import get_provider
from platform_core.notifications.services import NotificationService


logger = logging.getLogger(__name__)


class KYCService:
    """
    Service for managing KYC verification processes.
    """
    
    def __init__(self):
        self.notification_service = NotificationService()
    
    @transaction.atomic
    def initiate_verification(
        self,
        user,
        verification_type: str = 'INDIVIDUAL',
        verification_level: str = 'STANDARD',
        **kwargs
    ) -> KYCVerification:
        """
        Initiate KYC verification for a user.
        
        Args:
            user: User instance
            verification_type: Type of verification
            verification_level: Level of verification required
            **kwargs: Additional verification parameters
            
        Returns:
            KYCVerification instance
        """
        # Check for existing verification
        existing = KYCVerification.objects.filter(
            user=user,
            status__in=['VERIFIED', 'IN_PROGRESS']
        ).first()
        
        if existing and existing.is_valid:
            logger.info(f"Valid KYC verification already exists for user {user.id}")
            return existing
        
        # Create new verification
        verification = KYCVerification.objects.create(
            user=user,
            group=user.group,
            entity_type='user',
            entity_id=str(user.id),
            verification_type=verification_type,
            verification_level=verification_level,
            status='PENDING',
            required_documents=self._get_required_documents(
                verification_type, verification_level
            ),
            **kwargs
        )
        
        # Send notification
        self.notification_service.send_notification(
            user=user,
            notification_type='kyc_initiated',
            context={
                'verification_id': str(verification.id),
                'verification_type': verification_type
            }
        )
        
        logger.info(f"Initiated KYC verification {verification.id} for user {user.id}")
        return verification
    
    def _get_required_documents(
        self,
        verification_type: str,
        verification_level: str
    ) -> List[str]:
        """Get list of required documents based on verification type and level."""
        base_documents = ['identity_document', 'proof_of_address']
        
        if verification_type == 'BUSINESS':
            base_documents.extend([
                'company_registration',
                'tax_document',
                'bank_statement'
            ])
        
        if verification_level == 'ENHANCED':
            base_documents.extend([
                'source_of_funds',
                'financial_statements'
            ])
        
        return base_documents
    
    @transaction.atomic
    def submit_document(
        self,
        verification: KYCVerification,
        document_type: str,
        file_path: str,
        file_hash: str,
        **kwargs
    ) -> KYCDocument:
        """
        Submit a document for KYC verification.
        
        Args:
            verification: KYCVerification instance
            document_type: Type of document
            file_path: Path to stored file
            file_hash: SHA-256 hash of file
            **kwargs: Additional document metadata
            
        Returns:
            KYCDocument instance
        """
        # Create document record
        document = KYCDocument.objects.create(
            verification=verification,
            document_type=document_type,
            file_path=file_path,
            file_hash=file_hash,
            status='PENDING',
            **kwargs
        )
        
        # Update collected documents
        if document_type not in verification.collected_documents:
            verification.collected_documents.append(document_type)
            verification.save(update_fields=['collected_documents', 'updated_at'])
        
        # Trigger document verification
        verify_document_async.delay(document.id)
        
        logger.info(f"Document {document.id} submitted for verification {verification.id}")
        return document
    
    def verify_identity(
        self,
        verification: KYCVerification,
        provider_name: Optional[str] = None
    ) -> bool:
        """
        Perform identity verification using configured provider.
        
        Args:
            verification: KYCVerification instance
            provider_name: Optional provider override
            
        Returns:
            True if verification successful
        """
        if not provider_name:
            provider_name = self._select_provider(verification)
        
        try:
            provider = get_provider(provider_name)
            
            # Gather identity documents
            identity_docs = verification.documents.filter(
                document_type__in=['PASSPORT', 'DRIVERS_LICENSE', 'NATIONAL_ID'],
                status='APPROVED'
            )
            
            if not identity_docs.exists():
                logger.warning(f"No approved identity documents for verification {verification.id}")
                return False
            
            # Prepare document data
            documents = []
            for doc in identity_docs:
                documents.append({
                    'type': doc.document_type,
                    'number': doc.document_number,
                    'country': doc.issuing_country,
                    'extracted_data': doc.extracted_data
                })
            
            # Call provider
            result = provider.verify_identity(
                first_name=verification.first_name,
                last_name=verification.last_name,
                date_of_birth=verification.date_of_birth,
                documents=documents
            )
            
            # Update verification
            verification.identity_verified = result.verified
            verification.provider = provider_name
            verification.provider_reference = result.provider_reference
            verification.provider_data = result.raw_response
            
            if result.verified:
                verification.risk_score = result.risk_score
                logger.info(f"Identity verified for verification {verification.id}")
            else:
                logger.warning(f"Identity verification failed for {verification.id}: {result.errors}")
            
            verification.save()
            return result.verified
            
        except Exception as e:
            logger.error(f"Identity verification error for {verification.id}: {e}")
            return False
    
    def verify_address(
        self,
        verification: KYCVerification,
        provider_name: Optional[str] = None
    ) -> bool:
        """
        Perform address verification.
        
        Args:
            verification: KYCVerification instance
            provider_name: Optional provider override
            
        Returns:
            True if verification successful
        """
        if not provider_name:
            provider_name = self._select_provider(verification)
        
        try:
            provider = get_provider(provider_name)
            
            # Gather address documents
            address_docs = verification.documents.filter(
                document_type__in=['UTILITY_BILL', 'BANK_STATEMENT', 'PROOF_OF_ADDRESS'],
                status='APPROVED'
            )
            
            if not address_docs.exists():
                logger.warning(f"No approved address documents for verification {verification.id}")
                return False
            
            # Prepare document data
            documents = []
            for doc in address_docs:
                documents.append({
                    'type': doc.document_type,
                    'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
                    'extracted_data': doc.extracted_data
                })
            
            # Call provider
            result = provider.verify_address(
                address_line1=verification.address_line1,
                city=verification.city,
                country=verification.country,
                documents=documents
            )
            
            # Update verification
            verification.address_verified = result.verified
            
            if result.verified:
                logger.info(f"Address verified for verification {verification.id}")
            else:
                logger.warning(f"Address verification failed for {verification.id}: {result.errors}")
            
            verification.save()
            return result.verified
            
        except Exception as e:
            logger.error(f"Address verification error for {verification.id}: {e}")
            return False
    
    def complete_verification(self, verification: KYCVerification) -> bool:
        """
        Complete the KYC verification process.
        
        Args:
            verification: KYCVerification instance
            
        Returns:
            True if verification completed successfully
        """
        # Check all requirements met
        all_documents_collected = all(
            doc in verification.collected_documents
            for doc in verification.required_documents
        )
        
        if not all_documents_collected:
            logger.warning(f"Not all required documents collected for {verification.id}")
            return False
        
        # Check verification status
        if not (verification.identity_verified and verification.address_verified):
            logger.warning(f"Identity or address not verified for {verification.id}")
            return False
        
        # Update status
        verification.status = 'VERIFIED'
        verification.verified_at = timezone.now()
        verification.expires_at = timezone.now() + timedelta(days=365)  # 1 year validity
        verification.save()
        
        # Send notification
        if verification.user:
            self.notification_service.send_notification(
                user=verification.user,
                notification_type='kyc_completed',
                context={
                    'verification_id': str(verification.id),
                    'expires_at': verification.expires_at.isoformat()
                }
            )
        
        logger.info(f"KYC verification {verification.id} completed successfully")
        return True
    
    def _select_provider(self, verification: KYCVerification) -> str:
        """Select appropriate provider based on verification requirements."""
        # Simple selection logic - can be enhanced
        if verification.verification_type == 'BUSINESS':
            return 'onfido'  # Better for business verification
        elif verification.verification_level == 'ENHANCED':
            return 'refinitiv'  # Better for enhanced due diligence
        else:
            return 'onfido'  # Default for individual verification
    
    def get_verification_status(self, user) -> Dict[str, Any]:
        """
        Get current KYC verification status for a user.
        
        Args:
            user: User instance
            
        Returns:
            Status dictionary
        """
        verification = KYCVerification.objects.filter(
            user=user
        ).order_by('-created_at').first()
        
        if not verification:
            return {
                'status': 'NOT_STARTED',
                'verified': False,
                'expires_at': None,
                'required_documents': self._get_required_documents('INDIVIDUAL', 'STANDARD')
            }
        
        return {
            'status': verification.status,
            'verified': verification.is_valid,
            'expires_at': verification.expires_at,
            'days_until_expiry': verification.days_until_expiry,
            'required_documents': verification.required_documents,
            'collected_documents': verification.collected_documents,
            'missing_documents': [
                doc for doc in verification.required_documents
                if doc not in verification.collected_documents
            ],
            'verification_score': verification.calculate_verification_score()
        }
    
    def trigger_reverification(self, user) -> Optional[KYCVerification]:
        """
        Trigger reverification for expiring or expired KYC.
        
        Args:
            user: User instance
            
        Returns:
            New KYCVerification instance if triggered
        """
        current = KYCVerification.objects.filter(
            user=user,
            status='VERIFIED'
        ).order_by('-verified_at').first()
        
        if not current:
            logger.info(f"No verified KYC found for user {user.id}")
            return None
        
        days_until_expiry = current.days_until_expiry
        
        # Trigger if expiring within 30 days or already expired
        if days_until_expiry is not None and days_until_expiry <= 30:
            logger.info(f"Triggering KYC reverification for user {user.id}")
            
            # Create new verification
            new_verification = self.initiate_verification(
                user=user,
                verification_type=current.verification_type,
                verification_level=current.verification_level
            )
            
            # Copy relevant data from previous verification
            new_verification.first_name = current.first_name
            new_verification.last_name = current.last_name
            new_verification.date_of_birth = current.date_of_birth
            new_verification.nationality = current.nationality
            new_verification.save()
            
            return new_verification
        
        return None


@shared_task
def verify_document_async(document_id: str):
    """Async task to verify a document."""
    try:
        document = KYCDocument.objects.get(id=document_id)
        verification = document.verification
        
        # Select provider
        provider_name = 'onfido'  # Default provider for document verification
        provider = get_provider(provider_name)
        
        # Read document data (would integrate with file storage)
        # For now, using placeholder
        document_data = b"document_content_placeholder"
        
        # Verify document
        result = provider.verify_document(
            document_type=document.document_type,
            document_data=document_data
        )
        
        # Update document
        document.status = 'APPROVED' if result.document_authentic else 'REJECTED'
        document.extracted_data = result.data_extracted
        document.ocr_confidence = result.confidence_score * 100
        document.authenticity_score = int(result.confidence_score * 100)
        document.tampering_detected = result.tampering_detected
        document.validation_errors = result.errors or []
        document.verified_at = timezone.now()
        document.save()
        
        logger.info(f"Document {document_id} verification completed: {document.status}")
        
    except Exception as e:
        logger.error(f"Document verification error for {document_id}: {e}")


@shared_task
def check_kyc_expirations():
    """Daily task to check for expiring KYC verifications."""
    service = KYCService()
    
    # Find verifications expiring in next 30 days
    expiring_soon = KYCVerification.objects.filter(
        status='VERIFIED',
        expires_at__lte=timezone.now() + timedelta(days=30),
        expires_at__gt=timezone.now()
    )
    
    for verification in expiring_soon:
        if verification.user:
            # Send reminder notification
            days_left = (verification.expires_at - timezone.now()).days
            
            service.notification_service.send_notification(
                user=verification.user,
                notification_type='kyc_expiring',
                context={
                    'days_left': days_left,
                    'expires_at': verification.expires_at.isoformat()
                }
            )
            
            # Trigger reverification if within 7 days
            if days_left <= 7:
                service.trigger_reverification(verification.user)
    
    logger.info(f"Checked {expiring_soon.count()} expiring KYC verifications")