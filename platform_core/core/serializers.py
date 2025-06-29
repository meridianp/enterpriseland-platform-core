"""
Core serializers for the platform.
"""
from rest_framework import serializers


class PlatformSerializer(serializers.ModelSerializer):
    """
    Base serializer for platform models with common functionality.
    """
    
    def create(self, validated_data):
        """Create with automatic group assignment."""
        if 'group' not in validated_data and 'group' in self.context:
            validated_data['group'] = self.context['group']
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Update with group validation."""
        # Prevent changing group on update
        validated_data.pop('group', None)
        return super().update(instance, validated_data)