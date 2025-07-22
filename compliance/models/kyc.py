"""
KYC (Know Your Customer) Models

Models for identity verification and customer due diligence.
"""
import uuid
from datetime import datetime, timedelta
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.validators import MinValueValidator, MaxValueValidator
from platform_core.models import BaseModel, GroupFilteredModel
from platform_core.security.fields import EncryptedCharField, EncryptedJSONField


class KYCVerification(GroupFilteredModel):
    """
    Main KYC verification record for users and entities.
    """
    
    VERIFICATION_TYPE_CHOICES = [
        ('INDIVIDUAL', 'Individual Verification'),
        ('BUSINESS', 'Business Verification'),
        ('ENHANCED', 'Enhanced Due Diligence')
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending Verification'),
        ('IN_PROGRESS', 'In Progress'),
        ('VERIFIED', 'Verified'),
        ('FAILED', 'Failed'),
        ('EXPIRED', 'Expired'),
        ('SUSPENDED', 'Suspended')
    ]
    
    VERIFICATION_LEVEL_CHOICES = [
        ('BASIC', 'Basic KYC'),
        ('STANDARD', 'Standard KYC'),
        ('ENHANCED', 'Enhanced KYC')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='kyc_verifications',
        null=True, blank=True
    )
    entity_type = models.CharField(max_length=50, default='user')
    entity_id = models.CharField(max_length=100, db_index=True)
    
    # Verification Details
    verification_type = models.CharField(
        max_length=20, choices=VERIFICATION_TYPE_CHOICES
    )
    verification_level = models.CharField(
        max_length=20, choices=VERIFICATION_LEVEL_CHOICES, default='STANDARD'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='PENDING'
    )
    
    # Provider Information
    provider = models.CharField(max_length=50)
    provider_reference = models.CharField(max_length=255, blank=True)
    provider_data = EncryptedJSONField(default=dict, blank=True)
    
    # Verification Results
    verified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    risk_score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Personal Information (Encrypted)
    first_name = EncryptedCharField(max_length=100, blank=True)
    last_name = EncryptedCharField(max_length=100, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=2, blank=True)  # ISO country code
    
    # Address Information
    address_line1 = EncryptedCharField(max_length=255, blank=True)
    address_line2 = EncryptedCharField(max_length=255, blank=True)
    city = EncryptedCharField(max_length=100, blank=True)
    state_province = EncryptedCharField(max_length=100, blank=True)
    postal_code = EncryptedCharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True)  # ISO country code
    
    # Verification Flags
    identity_verified = models.BooleanField(default=False)
    address_verified = models.BooleanField(default=False)
    documents_verified = models.BooleanField(default=False)
    sanctions_cleared = models.BooleanField(default=False)
    pep_cleared = models.BooleanField(default=False)
    
    # Metadata
    verification_notes = models.TextField(blank=True)
    manual_review_required = models.BooleanField(default=False)
    manual_review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='kyc_reviews'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # Compliance Requirements
    required_documents = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True
    )
    collected_documents = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True
    )
    
    class Meta:
        db_table = 'compliance_kyc_verifications'
        verbose_name = 'KYC Verification'
        verbose_name_plural = 'KYC Verifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['user', 'status']),
        ]
    
    def __str__(self):
        return f"KYC Verification for {self.entity_type} {self.entity_id}"
    
    @property
    def is_valid(self):
        """Check if verification is currently valid."""
        if self.status != 'VERIFIED':
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True
    
    @property
    def days_until_expiry(self):
        """Calculate days until verification expires."""
        if not self.expires_at:
            return None
        delta = self.expires_at - timezone.now()
        return delta.days if delta.days > 0 else 0
    
    def calculate_verification_score(self):
        """Calculate overall verification score."""
        score = 0
        max_score = 100
        
        # Identity verification (40 points)
        if self.identity_verified:
            score += 40
        
        # Address verification (20 points)
        if self.address_verified:
            score += 20
        
        # Document verification (20 points)
        if self.documents_verified:
            score += 20
        
        # Sanctions/PEP clearance (20 points)
        if self.sanctions_cleared:
            score += 10
        if self.pep_cleared:
            score += 10
        
        return score


class KYCDocument(BaseModel):
    """
    Documents submitted for KYC verification.
    """
    
    DOCUMENT_TYPE_CHOICES = [
        ('PASSPORT', 'Passport'),
        ('DRIVERS_LICENSE', 'Driver\'s License'),
        ('NATIONAL_ID', 'National ID Card'),
        ('UTILITY_BILL', 'Utility Bill'),
        ('BANK_STATEMENT', 'Bank Statement'),
        ('TAX_DOCUMENT', 'Tax Document'),
        ('COMPANY_REGISTRATION', 'Company Registration'),
        ('PROOF_OF_ADDRESS', 'Proof of Address'),
        ('OTHER', 'Other Document')
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.ForeignKey(
        KYCVerification,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    
    # Document Details
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    document_number = EncryptedCharField(max_length=100, blank=True)
    issuing_country = models.CharField(max_length=2, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    
    # File Information
    file_path = models.CharField(max_length=500)
    file_hash = models.CharField(max_length=64)  # SHA-256 hash
    file_size = models.IntegerField()
    mime_type = models.CharField(max_length=100)
    
    # Verification Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='verified_documents'
    )
    
    # Extracted Data (Encrypted)
    extracted_data = EncryptedJSONField(default=dict, blank=True)
    ocr_confidence = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Validation
    authenticity_score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    tampering_detected = models.BooleanField(default=False)
    validation_errors = JSONField(default=list, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'compliance_kyc_documents'
        verbose_name = 'KYC Document'
        verbose_name_plural = 'KYC Documents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['verification', 'status']),
            models.Index(fields=['document_type', 'status']),
            models.Index(fields=['expiry_date']),
        ]
    
    def __str__(self):
        return f"{self.document_type} for {self.verification}"
    
    @property
    def is_expired(self):
        """Check if document is expired."""
        if not self.expiry_date:
            return False
        return self.expiry_date < timezone.now().date()


class IdentityDocument(BaseModel):
    """
    Specific identity document verification details.
    """
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kyc_document = models.OneToOneField(
        KYCDocument,
        on_delete=models.CASCADE,
        related_name='identity_details'
    )
    
    # Biometric Data (Encrypted)
    face_image = models.CharField(max_length=500, blank=True)  # Path to encrypted image
    face_match_score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Document Security Features
    mrz_verified = models.BooleanField(default=False)
    chip_verified = models.BooleanField(default=False)
    hologram_verified = models.BooleanField(default=False)
    watermark_verified = models.BooleanField(default=False)
    
    # Liveness Detection
    liveness_check_performed = models.BooleanField(default=False)
    liveness_score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Additional Verification
    document_template_matched = models.BooleanField(default=False)
    fonts_verified = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'compliance_identity_documents'
        verbose_name = 'Identity Document'
        verbose_name_plural = 'Identity Documents'


class AddressProof(BaseModel):
    """
    Address verification details.
    """
    
    PROOF_TYPE_CHOICES = [
        ('UTILITY_BILL', 'Utility Bill'),
        ('BANK_STATEMENT', 'Bank Statement'),
        ('RENTAL_AGREEMENT', 'Rental Agreement'),
        ('PROPERTY_DEED', 'Property Deed'),
        ('TAX_BILL', 'Tax Bill'),
        ('GOVERNMENT_LETTER', 'Government Letter')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kyc_document = models.OneToOneField(
        KYCDocument,
        on_delete=models.CASCADE,
        related_name='address_details'
    )
    
    # Proof Details
    proof_type = models.CharField(max_length=30, choices=PROOF_TYPE_CHOICES)
    issuer_name = models.CharField(max_length=255)
    issue_date = models.DateField()
    
    # Address Extraction
    extracted_address = EncryptedJSONField(default=dict)
    address_match_score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Validation
    issuer_verified = models.BooleanField(default=False)
    format_verified = models.BooleanField(default=False)
    recency_verified = models.BooleanField(default=False)  # Within last 3 months
    
    class Meta:
        db_table = 'compliance_address_proofs'
        verbose_name = 'Address Proof'
        verbose_name_plural = 'Address Proofs'


class BusinessVerification(GroupFilteredModel):
    """
    Business entity verification and due diligence.
    """
    
    BUSINESS_TYPE_CHOICES = [
        ('CORPORATION', 'Corporation'),
        ('LLC', 'Limited Liability Company'),
        ('PARTNERSHIP', 'Partnership'),
        ('TRUST', 'Trust'),
        ('FOUNDATION', 'Foundation'),
        ('OTHER', 'Other Entity Type')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kyc_verification = models.OneToOneField(
        KYCVerification,
        on_delete=models.CASCADE,
        related_name='business_details'
    )
    
    # Business Information
    legal_name = EncryptedCharField(max_length=255)
    trading_name = EncryptedCharField(max_length=255, blank=True)
    business_type = models.CharField(max_length=20, choices=BUSINESS_TYPE_CHOICES)
    
    # Registration Details
    registration_number = EncryptedCharField(max_length=100)
    registration_country = models.CharField(max_length=2)
    registration_date = models.DateField(null=True, blank=True)
    
    # Tax Information
    tax_id = EncryptedCharField(max_length=100, blank=True)
    vat_number = EncryptedCharField(max_length=100, blank=True)
    
    # Ownership Structure
    ownership_structure = EncryptedJSONField(default=dict)
    beneficial_owners = EncryptedJSONField(default=list)
    ownership_verified = models.BooleanField(default=False)
    
    # Business Verification
    registration_verified = models.BooleanField(default=False)
    good_standing_verified = models.BooleanField(default=False)
    financial_statements_verified = models.BooleanField(default=False)
    
    # Risk Factors
    high_risk_jurisdiction = models.BooleanField(default=False)
    complex_structure = models.BooleanField(default=False)
    shell_company_indicators = models.BooleanField(default=False)
    
    # Additional Information
    business_description = models.TextField(blank=True)
    primary_business_activity = models.CharField(max_length=255, blank=True)
    annual_revenue_range = models.CharField(max_length=50, blank=True)
    employee_count_range = models.CharField(max_length=50, blank=True)
    
    class Meta:
        db_table = 'compliance_business_verifications'
        verbose_name = 'Business Verification'
        verbose_name_plural = 'Business Verifications'
        
    def __str__(self):
        return f"Business Verification for {self.legal_name}"