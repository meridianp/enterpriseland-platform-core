"""
Example Models Using Encrypted Fields

Demonstrates how to use encrypted fields in Django models.
"""

from django.db import models
from django.contrib.auth import get_user_model

from platform_core.common.models import TenantFilteredModel
from .fields import (
    EncryptedCharField, EncryptedTextField, EncryptedEmailField,
    EncryptedIntegerField, EncryptedDecimalField, EncryptedDateField,
    EncryptedJSONField, EncryptedBooleanField
)

User = get_user_model()


class PersonalInformation(TenantFilteredModel):
    """
    Example model storing encrypted personal information.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='personal_info'
    )
    
    # Searchable encrypted fields (deterministic)
    email = EncryptedEmailField(
        searchable=True,
        deterministic=True,
        help_text="Searchable encrypted email"
    )
    
    ssn = EncryptedCharField(
        max_length=11,
        searchable=True,
        deterministic=True,
        help_text="Social Security Number (searchable)"
    )
    
    # Non-searchable encrypted fields (more secure)
    phone_number = EncryptedCharField(
        max_length=20,
        blank=True,
        help_text="Encrypted phone number"
    )
    
    date_of_birth = EncryptedDateField(
        null=True,
        blank=True,
        help_text="Encrypted date of birth"
    )
    
    annual_income = EncryptedDecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Encrypted annual income"
    )
    
    medical_notes = EncryptedTextField(
        blank=True,
        help_text="Encrypted medical information"
    )
    
    preferences = EncryptedJSONField(
        default=dict,
        help_text="Encrypted user preferences"
    )
    
    is_verified = EncryptedBooleanField(
        default=False,
        help_text="Encrypted verification status"
    )
    
    class Meta:
        db_table = 'security_personal_information'
        indexes = [
            models.Index(fields=['_email_hash']),  # Auto-created for searchable field
            models.Index(fields=['_ssn_hash']),    # Auto-created for searchable field
        ]
    
    def __str__(self):
        return f"Personal info for {self.user}"


class PaymentMethod(TenantFilteredModel):
    """
    Example model for encrypted payment information.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payment_methods'
    )
    
    nickname = models.CharField(
        max_length=100,
        help_text="Display name (not encrypted)"
    )
    
    # Highly sensitive - never searchable
    card_number = EncryptedCharField(
        max_length=19,
        help_text="Full card number (encrypted)"
    )
    
    card_holder = EncryptedCharField(
        max_length=100,
        help_text="Card holder name (encrypted)"
    )
    
    expiry_date = EncryptedCharField(
        max_length=7,  # MM/YYYY
        help_text="Card expiry date (encrypted)"
    )
    
    cvv = EncryptedCharField(
        max_length=4,
        help_text="CVV code (encrypted)"
    )
    
    # Searchable for lookups
    last_four = models.CharField(
        max_length=4,
        db_index=True,
        help_text="Last 4 digits (unencrypted for display)"
    )
    
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'security_payment_methods'
        ordering = ['-is_default', '-created_at']
    
    def save(self, *args, **kwargs):
        # Extract last four before encryption
        if self.card_number and not self.last_four:
            # This happens before field encryption
            self.last_four = self.card_number[-4:]
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.nickname} (*{self.last_four})"


class HealthRecord(TenantFilteredModel):
    """
    Example model for encrypted health records.
    """
    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='health_records'
    )
    
    record_type = models.CharField(
        max_length=50,
        choices=[
            ('diagnosis', 'Diagnosis'),
            ('prescription', 'Prescription'),
            ('test_result', 'Test Result'),
            ('allergy', 'Allergy'),
            ('immunization', 'Immunization'),
        ]
    )
    
    # All health data is encrypted
    condition_name = EncryptedCharField(
        max_length=200,
        searchable=True,  # Allow searching by condition
        deterministic=True
    )
    
    description = EncryptedTextField()
    
    diagnosis_date = EncryptedDateField()
    
    severity = EncryptedCharField(
        max_length=20,
        blank=True,
        choices=[
            ('mild', 'Mild'),
            ('moderate', 'Moderate'),
            ('severe', 'Severe'),
            ('critical', 'Critical'),
        ]
    )
    
    treatment_notes = EncryptedTextField(blank=True)
    
    test_results = EncryptedJSONField(
        default=dict,
        blank=True,
        help_text="Structured test results"
    )
    
    is_active = EncryptedBooleanField(
        default=True,
        help_text="Whether condition is current"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'security_health_records'
        ordering = ['-diagnosis_date', '-created_at']
        indexes = [
            models.Index(fields=['record_type']),
            models.Index(fields=['_condition_name_hash']),  # For searching
        ]
    
    def __str__(self):
        return f"{self.record_type}: {self.patient}"


class AuditLogEncrypted(TenantFilteredModel):
    """
    Example of selectively encrypting audit log fields.
    """
    action = models.CharField(max_length=50)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Encrypt sensitive details
    ip_address = EncryptedCharField(
        max_length=45,  # IPv6 max length
        searchable=True,
        deterministic=True,
        help_text="Encrypted IP for privacy"
    )
    
    user_agent = EncryptedTextField(
        blank=True,
        help_text="Encrypted browser info"
    )
    
    # Sensitive action details
    details = EncryptedJSONField(
        default=dict,
        help_text="Encrypted action details"
    )
    
    # Keep some data unencrypted for performance
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    success = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'security_audit_log_encrypted'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['_ip_address_hash']),  # For IP-based queries
        ]