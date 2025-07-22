"""
Source Catalogue API Views

API endpoints for accessing and managing the market intelligence
source catalogue with real-time accuracy metrics.
"""
import logging
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Avg, Count
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend

from ..models import (
    NewsSource, SourceCategory, SourceAccuracy,
    SourceHealth, EntityExtraction, SourceAlert
)
from ..serializers import (
    NewsSourceSerializer, SourceCategorySerializer,
    SourceAccuracySerializer, SourceHealthSerializer,
    EntityExtractionSerializer, SourceAlertSerializer
)
from ..services.source_catalogue import SourceCatalogueService
from core.permissions import IsAnalystOrAbove


logger = logging.getLogger(__name__)


class SourceCatalogueViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing news sources in the catalogue.
    
    Provides:
    - CRUD operations for sources
    - Accuracy metrics and dashboards
    - Health monitoring
    - Source categorization
    - Export functionality
    """
    
    queryset = NewsSource.objects.select_related(
        'accuracy', 'health'
    ).prefetch_related('categories')
    serializer_class = NewsSourceSerializer
    permission_classes = [IsAuthenticated, IsAnalystOrAbove]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['source_type', 'language', 'country', 'is_active']
    search_fields = ['name', 'url', 'tags']
    ordering_fields = ['quality_score', 'name', 'created_at']
    ordering = ['-quality_score']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.catalogue_service = SourceCatalogueService()
    
    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """
        Get source catalogue dashboard with overall metrics.
        
        Query Parameters:
        - time_range: Time range for metrics (1d, 7d, 30d)
        - group_by: Grouping option (source, category, type)
        """
        time_range = request.query_params.get('time_range', '7d')
        group_by = request.query_params.get('group_by', 'source')
        
        try:
            dashboard_data = self.catalogue_service.get_accuracy_dashboard(
                time_range=time_range,
                group_by=group_by
            )
            
            return Response(dashboard_data)
            
        except Exception as e:
            logger.error(f"Dashboard generation error: {e}")
            return Response(
                {'error': 'Failed to generate dashboard'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def accuracy_report(self, request):
        """
        Get detailed accuracy report for all sources.
        
        Query Parameters:
        - start_date: Start date for report
        - end_date: End date for report
        - min_accuracy: Minimum accuracy threshold
        """
        # Get parameters
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        min_accuracy = float(request.query_params.get('min_accuracy', 0))
        
        # Build query
        sources = self.get_queryset().filter(
            accuracy__entity_accuracy__gte=min_accuracy
        )
        
        # Build report
        report = {
            'generated_at': timezone.now().isoformat(),
            'parameters': {
                'start_date': start_date,
                'end_date': end_date,
                'min_accuracy': min_accuracy
            },
            'summary': {
                'total_sources': sources.count(),
                'average_accuracy': sources.aggregate(
                    avg=Avg('accuracy__entity_accuracy')
                )['avg'] or 0,
                'sources_above_90': sources.filter(
                    accuracy__entity_accuracy__gte=90
                ).count(),
                'sources_below_70': sources.filter(
                    accuracy__entity_accuracy__lt=70
                ).count()
            },
            'sources': []
        }
        
        # Add source details
        for source in sources[:100]:  # Limit for performance
            report['sources'].append({
                'id': str(source.id),
                'name': source.name,
                'type': source.source_type,
                'quality_score': source.quality_score,
                'accuracy': {
                    'entity': source.accuracy.entity_accuracy,
                    'sentiment': source.accuracy.sentiment_accuracy,
                    'classification': source.accuracy.classification_accuracy
                },
                'health': {
                    'status': source.health.status,
                    'uptime': source.health.uptime_percentage
                },
                'metrics': {
                    'total_articles': source.accuracy.total_articles,
                    'total_entities': source.accuracy.total_entities
                }
            })
        
        return Response(report)
    
    @action(detail=True, methods=['get'])
    def accuracy_history(self, request, pk=None):
        """
        Get accuracy history for a specific source.
        
        Query Parameters:
        - days: Number of days to include (default: 30)
        """
        source = self.get_object()
        days = int(request.query_params.get('days', 30))
        
        # Get entity extractions
        extractions = EntityExtraction.objects.filter(
            source=source,
            extraction_timestamp__gte=timezone.now() - timezone.timedelta(days=days),
            accuracy_score__isnull=False
        ).order_by('extraction_timestamp')
        
        # Build history
        history = {
            'source_id': str(source.id),
            'source_name': source.name,
            'period': f'{days} days',
            'current_accuracy': {
                'entity': source.accuracy.entity_accuracy,
                'sentiment': source.accuracy.sentiment_accuracy,
                'classification': source.accuracy.classification_accuracy
            },
            'history': []
        }
        
        # Add extraction history
        for extraction in extractions:
            history['history'].append({
                'timestamp': extraction.extraction_timestamp.isoformat(),
                'accuracy': extraction.accuracy_score,
                'entity_count': extraction.entity_count,
                'article_id': extraction.article_id
            })
        
        return Response(history)
    
    @action(detail=True, methods=['post'])
    def track_extraction(self, request, pk=None):
        """
        Track entity extraction results for accuracy monitoring.
        
        Request Body:
        {
            "article_id": "article-123",
            "extracted_entities": [...],
            "verified_entities": [...]  // Optional
        }
        """
        source = self.get_object()
        
        # Validate request data
        article_id = request.data.get('article_id')
        extracted_entities = request.data.get('extracted_entities', [])
        verified_entities = request.data.get('verified_entities')
        
        if not article_id:
            return Response(
                {'error': 'article_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Track extraction
            extraction = self.catalogue_service.track_entity_extraction(
                source=source,
                article_id=article_id,
                extracted_entities=extracted_entities,
                verified_entities=verified_entities
            )
            
            # Serialize response
            serializer = EntityExtractionSerializer(extraction)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Extraction tracking error: {e}")
            return Response(
                {'error': 'Failed to track extraction'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def update_health(self, request, pk=None):
        """
        Update source health status.
        
        Request Body:
        {
            "crawl_success": true,
            "response_time": 1.23,
            "error_message": null
        }
        """
        source = self.get_object()
        
        # Get health update data
        crawl_success = request.data.get('crawl_success', True)
        response_time = request.data.get('response_time')
        error_message = request.data.get('error_message')
        
        try:
            # Update health
            self.catalogue_service.update_source_health(
                source=source,
                crawl_success=crawl_success,
                response_time=response_time,
                error_message=error_message
            )
            
            # Return updated health
            source.refresh_from_db()
            serializer = SourceHealthSerializer(source.health)
            return Response(serializer.data)
            
        except Exception as e:
            logger.error(f"Health update error: {e}")
            return Response(
                {'error': 'Failed to update health'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def bulk_register(self, request):
        """
        Bulk register multiple sources.
        
        Request Body:
        {
            "sources": [
                {
                    "name": "Source Name",
                    "url": "https://example.com",
                    "source_type": "NEWS",
                    ...
                }
            ]
        }
        """
        sources_data = request.data.get('sources', [])
        
        if not sources_data:
            return Response(
                {'error': 'No sources provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        registered = []
        errors = []
        
        for source_data in sources_data:
            try:
                source = self.catalogue_service.register_source(**source_data)
                registered.append({
                    'id': str(source.id),
                    'name': source.name,
                    'status': 'registered'
                })
            except Exception as e:
                errors.append({
                    'name': source_data.get('name', 'Unknown'),
                    'error': str(e)
                })
        
        return Response({
            'registered': registered,
            'errors': errors,
            'summary': {
                'total': len(sources_data),
                'successful': len(registered),
                'failed': len(errors)
            }
        })
    
    @action(detail=False, methods=['get'])
    def export(self, request):
        """
        Export source catalogue.
        
        Query Parameters:
        - format: Export format (json, csv, excel)
        - include_inactive: Include inactive sources
        """
        export_format = request.query_params.get('format', 'json')
        include_inactive = request.query_params.get('include_inactive', 'false').lower() == 'true'
        
        try:
            file_path = self.catalogue_service.export_catalogue(
                format=export_format,
                include_inactive=include_inactive
            )
            
            # In production, would upload to S3 and return URL
            return Response({
                'status': 'success',
                'file_path': file_path,
                'format': export_format,
                'message': f'Catalogue exported to {file_path}'
            })
            
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Export error: {e}")
            return Response(
                {'error': 'Failed to export catalogue'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def categories(self, request):
        """
        Get source categories with counts.
        """
        categories = SourceCategory.objects.annotate(
            source_count=Count('sources')
        ).filter(is_active=True)
        
        serializer = SourceCategorySerializer(categories, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def health_summary(self, request):
        """
        Get overall health summary of all sources.
        """
        health_stats = SourceHealth.objects.values('status').annotate(
            count=Count('id')
        )
        
        # Calculate percentages
        total = sum(stat['count'] for stat in health_stats)
        
        summary = {
            'total_sources': total,
            'status_distribution': {
                stat['status']: {
                    'count': stat['count'],
                    'percentage': round((stat['count'] / total * 100), 2) if total > 0 else 0
                }
                for stat in health_stats
            },
            'critical_sources': SourceHealth.objects.filter(
                status__in=['FAILED', 'DEGRADED']
            ).count(),
            'average_uptime': SourceHealth.objects.aggregate(
                avg=Avg('uptime_percentage')
            )['avg'] or 0
        }
        
        return Response(summary)
    
    @action(detail=False, methods=['get'])
    def alerts(self, request):
        """
        Get active source alerts.
        
        Query Parameters:
        - severity: Filter by severity
        - alert_type: Filter by alert type
        - unresolved_only: Show only unresolved alerts
        """
        # Build query
        queryset = SourceAlert.objects.select_related('source')
        
        # Apply filters
        severity = request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        
        alert_type = request.query_params.get('alert_type')
        if alert_type:
            queryset = queryset.filter(alert_type=alert_type)
        
        unresolved_only = request.query_params.get('unresolved_only', 'true').lower() == 'true'
        if unresolved_only:
            queryset = queryset.filter(is_resolved=False)
        
        # Order by severity and time
        severity_order = {
            'CRITICAL': 0,
            'ERROR': 1,
            'WARNING': 2,
            'INFO': 3
        }
        
        alerts = sorted(
            queryset,
            key=lambda x: (severity_order.get(x.severity, 999), x.created_at),
            reverse=True
        )
        
        serializer = SourceAlertSerializer(alerts[:50], many=True)  # Limit for performance
        return Response({
            'total_alerts': len(alerts),
            'displayed': len(serializer.data),
            'alerts': serializer.data
        })


class SourceCategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing source categories.
    """
    
    queryset = SourceCategory.objects.annotate(
        source_count=Count('sources')
    )
    serializer_class = SourceCategorySerializer
    permission_classes = [IsAuthenticated, IsAnalystOrAbove]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'source_count']
    ordering = ['name']


class EntityExtractionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing entity extraction history.
    """
    
    queryset = EntityExtraction.objects.select_related('source')
    serializer_class = EntityExtractionSerializer
    permission_classes = [IsAuthenticated, IsAnalystOrAbove]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['source', 'accuracy_score']
    ordering_fields = ['extraction_timestamp', 'accuracy_score']
    ordering = ['-extraction_timestamp']