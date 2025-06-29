"""
Module System Serializers
"""

from rest_framework import serializers
from .models import ModuleManifest, ModuleInstallation, ModuleDependency, ModuleEvent


class ModuleManifestSerializer(serializers.ModelSerializer):
    """Serializer for module manifests"""
    
    class Meta:
        model = ModuleManifest
        fields = [
            'id', 'module_id', 'name', 'description', 'version',
            'platform_version', 'author', 'author_email', 'website',
            'dependencies', 'permissions', 'entities', 'workflows',
            'ui_components', 'api_endpoints', 'resource_limits',
            'configuration_schema', 'pricing_model', 'tags',
            'is_active', 'is_certified', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_dependencies(self, value):
        """Validate dependency format"""
        for dep in value:
            if not isinstance(dep, str):
                raise serializers.ValidationError(
                    "Dependencies must be strings"
                )
            # Basic format validation
            if not dep or ' ' in dep:
                raise serializers.ValidationError(
                    f"Invalid dependency format: {dep}"
                )
        return value
    
    def validate_version(self, value):
        """Validate semantic version format"""
        import re
        pattern = r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$'
        if not re.match(pattern, value):
            raise serializers.ValidationError(
                "Version must follow semantic versioning (e.g., 1.0.0)"
            )
        return value


class ModuleDependencySerializer(serializers.ModelSerializer):
    """Serializer for module dependencies"""
    required_module_name = serializers.CharField(
        source='required_module.name',
        read_only=True
    )
    
    class Meta:
        model = ModuleDependency
        fields = [
            'id', 'required_module', 'required_module_name',
            'version_constraint', 'is_satisfied', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'is_satisfied']


class ModuleInstallationSerializer(serializers.ModelSerializer):
    """Serializer for module installations"""
    module_details = ModuleManifestSerializer(
        source='module',
        read_only=True
    )
    dependencies = ModuleDependencySerializer(
        many=True,
        read_only=True
    )
    installed_by_username = serializers.CharField(
        source='installed_by.username',
        read_only=True
    )
    
    class Meta:
        model = ModuleInstallation
        fields = [
            'id', 'module', 'module_details', 'status', 'configuration',
            'installed_at', 'installed_by', 'installed_by_username',
            'enabled_at', 'disabled_at', 'dependencies'
        ]
        read_only_fields = [
            'id', 'installed_at', 'installed_by',
            'enabled_at', 'disabled_at'
        ]
    
    def validate_configuration(self, value):
        """Validate configuration against module schema"""
        if self.instance and self.instance.module.configuration_schema:
            # TODO: Implement JSON schema validation
            pass
        return value


class ModuleEventSerializer(serializers.ModelSerializer):
    """Serializer for module events"""
    module_name = serializers.CharField(
        source='module.name',
        read_only=True
    )
    user_username = serializers.CharField(
        source='user.username',
        read_only=True,
        allow_null=True
    )
    
    class Meta:
        model = ModuleEvent
        fields = [
            'id', 'module', 'module_name', 'event_type',
            'user', 'user_username', 'event_data', 'occurred_at'
        ]
        read_only_fields = ['id', 'occurred_at']


class ModuleRegistrySerializer(serializers.Serializer):
    """Serializer for module registry information"""
    available_count = serializers.IntegerField()
    installed_count = serializers.IntegerField()
    available_modules = ModuleManifestSerializer(many=True)
    installed_modules = ModuleInstallationSerializer(many=True)


class ModuleHealthSerializer(serializers.Serializer):
    """Serializer for module health information"""
    status = serializers.ChoiceField(
        choices=['healthy', 'degraded', 'unhealthy']
    )
    total_modules = serializers.IntegerField()
    healthy_modules = serializers.IntegerField()
    unhealthy_modules = serializers.IntegerField()
    modules = serializers.ListField(
        child=serializers.DictField()
    )


class ModuleInstallRequestSerializer(serializers.Serializer):
    """Serializer for module installation requests"""
    module_id = serializers.CharField()
    configuration = serializers.JSONField(required=False, default=dict)
    
    def validate_module_id(self, value):
        """Validate module exists"""
        if not ModuleManifest.objects.filter(
            module_id=value,
            is_active=True
        ).exists():
            raise serializers.ValidationError(
                f"Module {value} not found or inactive"
            )
        return value