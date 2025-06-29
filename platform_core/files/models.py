
from django.db import models
import uuid
import os

def upload_to(instance, filename):
    """Generate upload path for assessment files"""
    return f"assessments/{instance.assessment.id}/{filename}"

class FileAttachment(models.Model):
    """File attachments for assessments"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey('assessments.Assessment', on_delete=models.CASCADE, related_name='attachments')
    
    file = models.FileField(upload_to=upload_to)
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    content_type = models.CharField(max_length=100)
    
    # S3 storage fields
    s3_bucket = models.CharField(max_length=255, blank=True)
    s3_key = models.CharField(max_length=500, blank=True)
    
    # Metadata
    uploaded_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='uploaded_files')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)
    
    # File categorization
    category = models.CharField(max_length=50, choices=[
        ('financial', 'Financial Documents'),
        ('legal', 'Legal Documents'),
        ('operational', 'Operational Documents'),
        ('technical', 'Technical Documents'),
        ('other', 'Other')
    ], default='other')
    
    class Meta:
        db_table = 'file_attachments'
        
    def __str__(self):
        return f"{self.filename} ({self.assessment})"
    
    @property
    def file_size_mb(self):
        """File size in megabytes"""
        return round(self.file_size / (1024 * 1024), 2)
    
    def delete(self, *args, **kwargs):
        """Override delete to remove file from storage"""
        if self.file:
            if os.path.isfile(self.file.path):
                os.remove(self.file.path)
        super().delete(*args, **kwargs)
