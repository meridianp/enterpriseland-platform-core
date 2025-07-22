"""Filters for document management API."""

import django_filters
from django.db.models import Q
from ...models import Document, Folder, DocumentTemplate


class DocumentFilter(django_filters.FilterSet):
    """Filter for documents."""
    
    name = django_filters.CharFilter(lookup_expr='icontains')
    description = django_filters.CharFilter(lookup_expr='icontains')
    file_extension = django_filters.CharFilter(lookup_expr='exact')
    category = django_filters.CharFilter(lookup_expr='exact')
    status = django_filters.ChoiceFilter(choices=Document._meta.get_field('status').choices)
    
    # Size filters
    size_min = django_filters.NumberFilter(field_name='size', lookup_expr='gte')
    size_max = django_filters.NumberFilter(field_name='size', lookup_expr='lte')
    
    # Date filters
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    updated_after = django_filters.DateTimeFilter(field_name='updated_at', lookup_expr='gte')
    updated_before = django_filters.DateTimeFilter(field_name='updated_at', lookup_expr='lte')
    
    # Tag filter
    has_tag = django_filters.CharFilter(method='filter_has_tag')
    
    # Lock status
    is_locked = django_filters.BooleanFilter()
    
    # Processing status
    virus_scanned = django_filters.BooleanFilter()
    preview_generated = django_filters.BooleanFilter()
    ocr_processed = django_filters.BooleanFilter()
    
    # User filters
    created_by = django_filters.UUIDFilter(field_name='created_by__id')
    locked_by = django_filters.UUIDFilter(field_name='locked_by__id')
    
    class Meta:
        model = Document
        fields = [
            'name', 'description', 'file_extension', 'category', 'status',
            'size_min', 'size_max', 'created_after', 'created_before',
            'updated_after', 'updated_before', 'has_tag', 'is_locked',
            'virus_scanned', 'preview_generated', 'ocr_processed',
            'created_by', 'locked_by', 'folder'
        ]
    
    def filter_has_tag(self, queryset, name, value):
        """Filter documents that have a specific tag."""
        return queryset.filter(tags__contains=[value])


class FolderFilter(django_filters.FilterSet):
    """Filter for folders."""
    
    name = django_filters.CharFilter(lookup_expr='icontains')
    description = django_filters.CharFilter(lookup_expr='icontains')
    is_system = django_filters.BooleanFilter()
    
    # Hierarchy filters
    parent = django_filters.UUIDFilter(field_name='parent__id')
    is_root = django_filters.BooleanFilter(method='filter_is_root')
    
    # Document count filters
    has_documents = django_filters.BooleanFilter(method='filter_has_documents')
    document_count_min = django_filters.NumberFilter(field_name='document_count', lookup_expr='gte')
    document_count_max = django_filters.NumberFilter(field_name='document_count', lookup_expr='lte')
    
    # User filters
    created_by = django_filters.UUIDFilter(field_name='created_by__id')
    
    class Meta:
        model = Folder
        fields = [
            'name', 'description', 'is_system', 'parent', 'is_root',
            'has_documents', 'document_count_min', 'document_count_max',
            'created_by'
        ]
    
    def filter_is_root(self, queryset, name, value):
        """Filter root folders."""
        if value:
            return queryset.filter(parent__isnull=True)
        else:
            return queryset.filter(parent__isnull=False)
    
    def filter_has_documents(self, queryset, name, value):
        """Filter folders that have documents."""
        if value:
            return queryset.filter(document_count__gt=0)
        else:
            return queryset.filter(document_count=0)


class TemplateFilter(django_filters.FilterSet):
    """Filter for document templates."""
    
    name = django_filters.CharFilter(lookup_expr='icontains')
    description = django_filters.CharFilter(lookup_expr='icontains')
    category = django_filters.CharFilter(lookup_expr='exact')
    file_type = django_filters.CharFilter(lookup_expr='exact')
    is_active = django_filters.BooleanFilter()
    is_system = django_filters.BooleanFilter()
    is_public = django_filters.BooleanFilter()
    
    # Usage filters
    used_after = django_filters.DateTimeFilter(field_name='last_used', lookup_expr='gte')
    usage_count_min = django_filters.NumberFilter(field_name='usage_count', lookup_expr='gte')
    
    class Meta:
        model = DocumentTemplate
        fields = [
            'name', 'description', 'category', 'file_type',
            'is_active', 'is_system', 'is_public',
            'used_after', 'usage_count_min'
        ]