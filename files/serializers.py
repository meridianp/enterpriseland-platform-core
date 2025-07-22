"""
Serializers for the files app.
"""
from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from .models import File, FileAccessLog


class FileSerializer(serializers.ModelSerializer):
    """Serializer for File model."""
    
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True)
    uploaded_by_email = serializers.EmailField(source='uploaded_by.email', read_only=True)
    file_size_display = serializers.CharField(read_only=True)
    download_url = serializers.SerializerMethodField()
    content_object_type = serializers.SerializerMethodField()
    content_object_display = serializers.SerializerMethodField()
    
    class Meta:
        model = File
        fields = [
            'id', 'filename', 'file_size', 'file_size_display',
            'content_type', 'category', 'description',
            'uploaded_by', 'uploaded_by_name', 'uploaded_by_email',
            'created_at', 'updated_at',
            'is_public', 'download_url',
            'content_object_type', 'content_object_display',
            'version', 'parent_file',
            'virus_scanned', 'virus_scan_result',
            'metadata'
        ]
        read_only_fields = [
            'id', 'file_size', 'content_type', 'uploaded_by',
            'created_at', 'updated_at', 'virus_scanned', 
            'virus_scan_result', 'virus_scanned_at'
        ]
    
    def get_download_url(self, obj):
        """Get temporary download URL."""
        request = self.context.get('request')
        if request and obj.has_access(request.user):
            return obj.get_download_url()
        return None
    
    def get_content_object_type(self, obj):
        """Get the type of the related object."""
        if obj.content_object:
            return f"{obj.content_type.app_label}.{obj.content_type.model}"
        return None
    
    def get_content_object_display(self, obj):
        """Get display representation of the related object."""
        if obj.content_object:
            return str(obj.content_object)
        return None


class FileUploadSerializer(serializers.ModelSerializer):
    """Serializer for file uploads."""
    
    file = serializers.FileField(write_only=True)
    content_type_name = serializers.CharField(write_only=True, required=False)
    object_id = serializers.UUIDField(write_only=True, required=False)
    
    class Meta:
        model = File
        fields = [
            'file', 'description', 'category', 'is_public',
            'content_type_name', 'object_id', 'metadata'
        ]
    
    def validate(self, attrs):
        """Validate file upload."""
        file = attrs.get('file')
        
        if file:
            # Store file info for later use
            attrs['filename'] = file.name
            attrs['file_size'] = file.size
            attrs['content_type'] = file.content_type or 'application/octet-stream'
        
        # Validate content object if provided
        content_type_name = attrs.pop('content_type_name', None)
        object_id = attrs.get('object_id')
        
        if content_type_name and object_id:
            try:
                app_label, model = content_type_name.split('.')
                content_type = ContentType.objects.get(
                    app_label=app_label,
                    model=model
                )
                attrs['content_type'] = content_type
                
                # Verify object exists
                model_class = content_type.model_class()
                if not model_class.objects.filter(pk=object_id).exists():
                    raise serializers.ValidationError(
                        f"Object with id {object_id} not found"
                    )
            except (ValueError, ContentType.DoesNotExist):
                raise serializers.ValidationError(
                    f"Invalid content type: {content_type_name}"
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create file with user from context."""
        validated_data['uploaded_by'] = self.context['request'].user
        return super().create(validated_data)


class FileAccessLogSerializer(serializers.ModelSerializer):
    """Serializer for file access logs."""
    
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    file_name = serializers.CharField(source='file.filename', read_only=True)
    
    class Meta:
        model = FileAccessLog
        fields = [
            'id', 'file', 'file_name', 'user', 'user_name', 'user_email',
            'action', 'timestamp', 'ip_address', 'user_agent', 'metadata'
        ]
        read_only_fields = ['id', 'timestamp']