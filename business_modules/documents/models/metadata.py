"""Document metadata models."""

from django.db import models
from django.contrib.postgres.fields import JSONField
from .base import TimestampedModel
from .document import Document


class DocumentMetadata(TimestampedModel):
    """Extended metadata for documents."""
    
    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name='metadata',
        help_text="Parent document"
    )
    
    # File metadata
    file_metadata = JSONField(
        default=dict,
        blank=True,
        help_text="Raw file metadata extracted"
    )
    
    # Document properties
    title = models.CharField(
        max_length=500,
        blank=True,
        help_text="Document title from metadata"
    )
    
    author = models.CharField(
        max_length=255,
        blank=True,
        help_text="Document author"
    )
    
    subject = models.CharField(
        max_length=500,
        blank=True,
        help_text="Document subject"
    )
    
    keywords = models.TextField(
        blank=True,
        help_text="Document keywords"
    )
    
    # Dates
    creation_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Document creation date from metadata"
    )
    
    modification_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Document modification date from metadata"
    )
    
    # Content statistics
    page_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of pages"
    )
    
    word_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of words"
    )
    
    character_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of characters"
    )
    
    # Media properties
    width = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Width in pixels (for images/videos)"
    )
    
    height = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Height in pixels (for images/videos)"
    )
    
    duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration in seconds (for audio/video)"
    )
    
    # Geographic data
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=8,
        null=True,
        blank=True,
        help_text="GPS latitude"
    )
    
    longitude = models.DecimalField(
        max_digits=11,
        decimal_places=8,
        null=True,
        blank=True,
        help_text="GPS longitude"
    )
    
    location_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Location name"
    )
    
    # Software information
    producer = models.CharField(
        max_length=255,
        blank=True,
        help_text="Software that created the document"
    )
    
    creator_tool = models.CharField(
        max_length=255,
        blank=True,
        help_text="Tool used to create the document"
    )
    
    # Custom metadata
    custom_fields = JSONField(
        default=dict,
        blank=True,
        help_text="Custom metadata fields"
    )
    
    # Extraction status
    extraction_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending',
        help_text="Metadata extraction status"
    )
    
    extraction_error = models.TextField(
        blank=True,
        help_text="Error message if extraction failed"
    )
    
    extracted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When metadata was extracted"
    )
    
    class Meta:
        verbose_name = "Document Metadata"
        verbose_name_plural = "Document Metadata"
        indexes = [
            models.Index(fields=['author']),
            models.Index(fields=['creation_date']),
            models.Index(fields=['extraction_status']),
        ]
    
    def __str__(self):
        return f"Metadata: {self.document.name}"
    
    def update_from_extraction(self, extracted_data):
        """Update metadata from extraction results."""
        # File metadata
        self.file_metadata = extracted_data.get('raw_metadata', {})
        
        # Document properties
        self.title = extracted_data.get('title', '')[:500]
        self.author = extracted_data.get('author', '')[:255]
        self.subject = extracted_data.get('subject', '')[:500]
        self.keywords = extracted_data.get('keywords', '')
        
        # Dates
        self.creation_date = extracted_data.get('creation_date')
        self.modification_date = extracted_data.get('modification_date')
        
        # Content statistics
        self.page_count = extracted_data.get('page_count')
        self.word_count = extracted_data.get('word_count')
        self.character_count = extracted_data.get('character_count')
        
        # Media properties
        self.width = extracted_data.get('width')
        self.height = extracted_data.get('height')
        self.duration = extracted_data.get('duration')
        
        # Geographic data
        self.latitude = extracted_data.get('latitude')
        self.longitude = extracted_data.get('longitude')
        self.location_name = extracted_data.get('location_name', '')[:255]
        
        # Software information
        self.producer = extracted_data.get('producer', '')[:255]
        self.creator_tool = extracted_data.get('creator_tool', '')[:255]
        
        # Custom fields
        custom = extracted_data.get('custom', {})
        if custom:
            self.custom_fields.update(custom)
        
        # Update status
        self.extraction_status = 'completed'
        self.extracted_at = models.functions.Now()
        
        self.save()
    
    def get_display_metadata(self):
        """Get metadata formatted for display."""
        metadata = {}
        
        # Basic information
        if self.title:
            metadata['Title'] = self.title
        if self.author:
            metadata['Author'] = self.author
        if self.subject:
            metadata['Subject'] = self.subject
        if self.keywords:
            metadata['Keywords'] = self.keywords
        
        # Dates
        if self.creation_date:
            metadata['Created'] = self.creation_date
        if self.modification_date:
            metadata['Modified'] = self.modification_date
        
        # Statistics
        if self.page_count:
            metadata['Pages'] = self.page_count
        if self.word_count:
            metadata['Words'] = self.word_count
        
        # Media
        if self.width and self.height:
            metadata['Dimensions'] = f"{self.width}x{self.height}"
        if self.duration:
            metadata['Duration'] = f"{self.duration}s"
        
        # Location
        if self.latitude and self.longitude:
            metadata['Location'] = f"{self.latitude}, {self.longitude}"
            if self.location_name:
                metadata['Location'] += f" ({self.location_name})"
        
        # Software
        if self.producer:
            metadata['Producer'] = self.producer
        
        # Add custom fields
        for key, value in self.custom_fields.items():
            if key not in metadata:
                metadata[key] = value
        
        return metadata