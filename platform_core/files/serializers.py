
from rest_framework import serializers
from platform_core.core.serializers import PlatformSerializer
from .models import FileAttachment

class FileAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for file attachments"""
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True)
    file_size_mb = serializers.ReadOnlyField()
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = FileAttachment
        fields = [
            'id', 'assessment', 'file', 'filename', 'file_size',
            'file_size_mb', 'content_type', 'category', 'description',
            'uploaded_by', 'uploaded_by_name', 'uploaded_at', 'file_url'
        ]
        read_only_fields = ['id', 'file_size', 'content_type', 'uploaded_by', 'uploaded_at']
    
    def get_file_url(self, obj):
        """Get file URL"""
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None
    
    def create(self, validated_data):
        """Create file attachment with metadata"""
        file_obj = validated_data['file']
        validated_data['filename'] = file_obj.name
        validated_data['file_size'] = file_obj.size
        validated_data['content_type'] = file_obj.content_type
        validated_data['uploaded_by'] = self.context['request'].user
        
        return super().create(validated_data)

class FileUploadSerializer(serializers.Serializer):
    """Serializer for file upload"""
    file = serializers.FileField()
    category = serializers.ChoiceField(
        choices=FileAttachment._meta.get_field('category').choices,
        default='other'
    )
    description = serializers.CharField(required=False, allow_blank=True)
