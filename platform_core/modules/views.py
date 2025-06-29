"""
Module System Views
"""

from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ModuleManifest, ModuleInstallation
from .serializers import (
    ModuleManifestSerializer,
    ModuleInstallationSerializer,
    ModuleRegistrySerializer,
    ModuleHealthSerializer,
)
from .registry import ModuleRegistry
from .exceptions import (
    ModuleError,
    ModuleAlreadyInstalled,
    DependencyNotSatisfied,
)


class ModuleManifestViewSet(viewsets.ModelViewSet):
    """
    ViewSet for module manifests.
    
    Provides CRUD operations for module manifests and
    additional actions for module lifecycle management.
    """
    serializer_class = ModuleManifestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['module_id', 'is_active', 'is_certified', 'pricing_model']
    search_fields = ['module_id', 'name', 'description', 'tags']
    ordering_fields = ['created_at', 'name', 'version']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get manifests based on user permissions"""
        queryset = ModuleManifest.objects.all()
        
        # Filter by active status unless user is admin
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a module manifest"""
        manifest = self.get_object()
        manifest.is_active = True
        manifest.save()
        
        serializer = self.get_serializer(manifest)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a module manifest"""
        manifest = self.get_object()
        manifest.is_active = False
        manifest.save()
        
        serializer = self.get_serializer(manifest)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def dependencies(self, request, pk=None):
        """Get module dependencies"""
        manifest = self.get_object()
        registry = ModuleRegistry()
        
        try:
            # Resolve full dependency tree
            all_deps = registry.resolve_dependencies([manifest.module_id])
            all_deps.remove(manifest.module_id)  # Remove self
            
            # Get manifest objects
            dep_manifests = ModuleManifest.objects.filter(
                module_id__in=all_deps
            )
            
            serializer = self.get_serializer(dep_manifests, many=True)
            return Response({
                'direct': manifest.dependencies,
                'resolved': all_deps,
                'manifests': serializer.data
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class ModuleInstallationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for module installations.
    
    Manages module installations per tenant with
    lifecycle operations like enable/disable.
    """
    serializer_class = ModuleInstallationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['module', 'status']
    ordering = ['-installed_at']
    
    def get_queryset(self):
        """Get installations for user's tenant"""
        return ModuleInstallation.objects.filter(
            tenant=self.request.user.tenant
        ).select_related('module', 'installed_by')
    
    def perform_create(self, serializer):
        """Install a module for the tenant"""
        registry = ModuleRegistry()
        module_id = self.request.data.get('module_id')
        
        if not module_id:
            raise ValueError("module_id is required")
        
        try:
            # Use registry to handle installation
            installation = registry.install_module(
                module_id=module_id,
                tenant=self.request.user.tenant,
                user=self.request.user
            )
            
            # Return the created installation
            serializer.instance = installation
            
        except ModuleAlreadyInstalled as e:
            raise serializers.ValidationError(str(e))
        except DependencyNotSatisfied as e:
            raise serializers.ValidationError(str(e))
        except Exception as e:
            raise serializers.ValidationError(f"Installation failed: {str(e)}")
    
    @action(detail=True, methods=['post'])
    def enable(self, request, pk=None):
        """Enable a module installation"""
        installation = self.get_object()
        registry = ModuleRegistry()
        
        try:
            registry.enable_module(
                installation.module.module_id,
                installation.tenant
            )
            
            installation.refresh_from_db()
            serializer = self.get_serializer(installation)
            return Response(serializer.data)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def disable(self, request, pk=None):
        """Disable a module installation"""
        installation = self.get_object()
        registry = ModuleRegistry()
        
        try:
            registry.disable_module(
                installation.module.module_id,
                installation.tenant
            )
            
            installation.refresh_from_db()
            serializer = self.get_serializer(installation)
            return Response(serializer.data)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['delete'])
    def uninstall(self, request, pk=None):
        """Uninstall a module"""
        installation = self.get_object()
        registry = ModuleRegistry()
        
        try:
            registry.uninstall_module(
                installation.module.module_id,
                installation.tenant
            )
            
            return Response(status=status.HTTP_204_NO_CONTENT)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def health(self, request, pk=None):
        """Get module health status"""
        installation = self.get_object()
        
        # TODO: Implement health checking
        health_data = {
            'status': 'healthy' if installation.is_active() else 'inactive',
            'last_checked': None,
            'metrics': {}
        }
        
        return Response(health_data)


class ModuleRegistryView(APIView):
    """
    Module registry operations.
    
    Provides registry-level operations like listing
    available modules and checking compatibility.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get registry information"""
        registry = ModuleRegistry()
        
        # Get available modules
        available = registry.list_available_modules()
        
        # Get installed modules for tenant
        installed = registry.list_installed_modules(request.user.tenant)
        
        serializer = ModuleRegistrySerializer({
            'available_count': available.count(),
            'installed_count': installed.count(),
            'available_modules': ModuleManifestSerializer(
                available, many=True
            ).data,
            'installed_modules': ModuleInstallationSerializer(
                installed, many=True
            ).data,
        })
        
        return Response(serializer.data)
    
    def post(self, request):
        """Register a new module"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can register modules'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        registry = ModuleRegistry()
        
        try:
            manifest = registry.register_module(request.data)
            serializer = ModuleManifestSerializer(manifest)
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class ModuleHealthView(APIView):
    """
    Module system health monitoring.
    
    Provides health status for all installed modules
    and the module system itself.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get overall module system health"""
        registry = ModuleRegistry()
        installations = registry.list_installed_modules(request.user.tenant)
        
        # Check each module's health
        module_health = []
        for installation in installations:
            if installation.is_active():
                # TODO: Implement actual health checking
                health = {
                    'module_id': installation.module.module_id,
                    'name': installation.module.name,
                    'status': 'healthy',
                    'last_checked': None,
                }
            else:
                health = {
                    'module_id': installation.module.module_id,
                    'name': installation.module.name,
                    'status': 'inactive',
                    'last_checked': None,
                }
            
            module_health.append(health)
        
        # Overall system health
        unhealthy_count = sum(1 for h in module_health if h['status'] != 'healthy')
        
        system_health = {
            'status': 'degraded' if unhealthy_count > 0 else 'healthy',
            'total_modules': len(module_health),
            'healthy_modules': len(module_health) - unhealthy_count,
            'unhealthy_modules': unhealthy_count,
            'modules': module_health,
        }
        
        serializer = ModuleHealthSerializer(system_health)
        return Response(serializer.data)