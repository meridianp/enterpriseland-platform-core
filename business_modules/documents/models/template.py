"""Document template models."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from .base import DocumentBaseModel

User = get_user_model()


class DocumentTemplate(DocumentBaseModel):
    """Document templates for creating standardized documents."""
    
    name = models.CharField(
        max_length=255,
        help_text="Template name"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Template description"
    )
    
    category = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Template category"
    )
    
    # Template file
    file_path = models.CharField(
        max_length=1000,
        help_text="Path to template file"
    )
    
    file_type = models.CharField(
        max_length=20,
        choices=[
            ('docx', 'Word Document'),
            ('xlsx', 'Excel Spreadsheet'),
            ('pptx', 'PowerPoint Presentation'),
            ('html', 'HTML'),
            ('pdf', 'PDF Form'),
            ('txt', 'Plain Text'),
        ],
        help_text="Template file type"
    )
    
    # Template configuration
    is_active = models.BooleanField(
        default=True,
        help_text="Whether template is available for use"
    )
    
    is_system = models.BooleanField(
        default=False,
        help_text="System template that cannot be modified"
    )
    
    # Usage tracking
    usage_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times template has been used"
    )
    
    last_used = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When template was last used"
    )
    
    # Preview
    preview_image = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Path to preview image"
    )
    
    # Metadata
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Template tags"
    )
    
    # Access control
    is_public = models.BooleanField(
        default=True,
        help_text="Whether template is available to all users"
    )
    
    allowed_groups = models.ManyToManyField(
        'auth.Group',
        blank=True,
        help_text="Groups allowed to use this template"
    )
    
    allowed_users = models.ManyToManyField(
        User,
        blank=True,
        related_name='allowed_templates',
        help_text="Specific users allowed to use this template"
    )
    
    class Meta:
        verbose_name = "Document Template"
        verbose_name_plural = "Document Templates"
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['is_active', 'is_public']),
        ]
    
    def __str__(self):
        return self.name
    
    def can_use(self, user):
        """Check if user can use this template."""
        if not self.is_active:
            return False
        
        if self.is_public:
            return True
        
        if self.allowed_users.filter(id=user.id).exists():
            return True
        
        if user.groups.filter(id__in=self.allowed_groups.all()).exists():
            return True
        
        return False
    
    def increment_usage(self):
        """Increment usage counter."""
        from django.utils import timezone
        self.usage_count = models.F('usage_count') + 1
        self.last_used = timezone.now()
        self.save(update_fields=['usage_count', 'last_used'])
    
    def get_fields(self):
        """Get all fields defined in this template."""
        return self.fields.filter(is_active=True).order_by('order')
    
    def create_document_from_template(self, user, data, folder=None):
        """Create a new document from this template with field substitution."""
        from ..services import DocumentService
        
        # Increment usage
        self.increment_usage()
        
        # Create document from template
        document_service = DocumentService()
        document = document_service.create_from_template(
            template=self,
            user=user,
            data=data,
            folder=folder
        )
        
        return document


class TemplateField(models.Model):
    """Fields that can be filled in templates."""
    
    template = models.ForeignKey(
        DocumentTemplate,
        on_delete=models.CASCADE,
        related_name='fields',
        help_text="Parent template"
    )
    
    name = models.CharField(
        max_length=100,
        help_text="Field name/identifier"
    )
    
    label = models.CharField(
        max_length=255,
        help_text="Field label for display"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Field description/help text"
    )
    
    field_type = models.CharField(
        max_length=20,
        choices=[
            ('text', 'Text'),
            ('number', 'Number'),
            ('date', 'Date'),
            ('datetime', 'Date & Time'),
            ('boolean', 'Yes/No'),
            ('choice', 'Choice'),
            ('multichoice', 'Multiple Choice'),
            ('email', 'Email'),
            ('url', 'URL'),
            ('textarea', 'Long Text'),
            ('file', 'File Reference'),
            ('user', 'User Reference'),
            ('formula', 'Formula'),
        ],
        default='text',
        help_text="Field data type"
    )
    
    # Field configuration
    is_required = models.BooleanField(
        default=False,
        help_text="Whether field is required"
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether field is active"
    )
    
    default_value = models.TextField(
        blank=True,
        help_text="Default value for field"
    )
    
    # Validation
    validation_rules = models.JSONField(
        default=dict,
        blank=True,
        help_text="Field validation rules"
    )
    
    # For choice fields
    choices = models.JSONField(
        default=list,
        blank=True,
        help_text="Available choices for choice fields"
    )
    
    # Display
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order"
    )
    
    placeholder = models.CharField(
        max_length=255,
        blank=True,
        help_text="Placeholder text"
    )
    
    # Mapping
    document_property = models.CharField(
        max_length=100,
        blank=True,
        help_text="Maps to document property"
    )
    
    template_variable = models.CharField(
        max_length=100,
        blank=True,
        help_text="Variable name in template"
    )
    
    class Meta:
        verbose_name = "Template Field"
        verbose_name_plural = "Template Fields"
        unique_together = [['template', 'name']]
        ordering = ['order', 'name']
    
    def __str__(self):
        return f"{self.template.name} - {self.label}"
    
    def validate_value(self, value):
        """Validate a value against field rules."""
        if self.is_required and not value:
            raise ValueError(f"{self.label} is required")
        
        if not value:
            return True
        
        # Type-specific validation
        if self.field_type == 'number':
            try:
                float(value)
            except ValueError:
                raise ValueError(f"{self.label} must be a number")
        
        elif self.field_type == 'email':
            from django.core.validators import validate_email
            validate_email(value)
        
        elif self.field_type == 'url':
            from django.core.validators import URLValidator
            validator = URLValidator()
            validator(value)
        
        elif self.field_type in ['choice', 'multichoice'] and self.choices:
            valid_choices = [c['value'] for c in self.choices if isinstance(c, dict)]
            if self.field_type == 'choice':
                if value not in valid_choices:
                    raise ValueError(f"Invalid choice for {self.label}")
            else:
                # Multiple choice
                values = value if isinstance(value, list) else [value]
                for v in values:
                    if v not in valid_choices:
                        raise ValueError(f"Invalid choice '{v}' for {self.label}")
        
        # Custom validation rules
        if self.validation_rules:
            # Implement custom validation based on rules
            pass
        
        return True