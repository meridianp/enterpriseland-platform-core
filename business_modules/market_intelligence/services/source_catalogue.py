"""
Market Intelligence Source Catalogue Service

Manages and publishes the catalogue of 1000+ news sources with
real-time accuracy tracking and source health monitoring.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from django.db import transaction, models
from django.db.models import Q, Count, Avg, F, Sum
from django.utils import timezone
from django.core.cache import cache
from celery import shared_task
import json
import requests
from collections import defaultdict

from ..models import (
    NewsSource, SourceAccuracy, EntityExtraction,
    SourceHealth, SourceCategory, SourceMetrics
)
from platform_core.notifications.services import NotificationService
from platform_core.websocket.services import WebSocketService


logger = logging.getLogger(__name__)


class SourceCatalogueService:
    """
    Service for managing and publishing the market intelligence source catalogue.
    
    Features:
    - Source discovery and registration
    - Real-time accuracy tracking
    - Entity extraction metrics
    - Source health monitoring
    - Performance dashboards
    - Source categorization
    - Quality scoring
    """
    
    def __init__(self):
        self.notification_service = NotificationService()
        self.websocket_service = WebSocketService()
    
    @transaction.atomic
    def register_source(
        self,
        name: str,
        url: str,
        source_type: str = 'NEWS',
        **kwargs
    ) -> 'NewsSource':
        """
        Register a new source in the catalogue.
        
        Args:
            name: Source name
            url: Source URL or API endpoint
            source_type: Type of source
            **kwargs: Additional source configuration
            
        Returns:
            NewsSource instance
        """
        # Check for duplicates
        existing = NewsSource.objects.filter(
            Q(url=url) | Q(name=name)
        ).first()
        
        if existing:
            logger.warning(f"Source already exists: {name} ({url})")
            return existing
        
        # Create source
        source = NewsSource.objects.create(
            name=name,
            url=url,
            source_type=source_type,
            feed_url=kwargs.get('feed_url', url),
            api_key=kwargs.get('api_key', ''),
            is_active=kwargs.get('is_active', True),
            language=kwargs.get('language', 'en'),
            country=kwargs.get('country', 'US'),
            categories=kwargs.get('categories', []),
            tags=kwargs.get('tags', []),
            configuration=kwargs.get('configuration', {}),
            crawl_frequency=kwargs.get('crawl_frequency', 3600),
            quality_score=0.0  # Will be calculated
        )
        
        # Initialize accuracy tracking
        SourceAccuracy.objects.create(
            source=source,
            entity_accuracy=0.0,
            sentiment_accuracy=0.0,
            classification_accuracy=0.0,
            total_articles=0,
            total_entities=0
        )
        
        # Initialize health monitoring
        SourceHealth.objects.create(
            source=source,
            status='HEALTHY',
            uptime_percentage=100.0,
            last_successful_crawl=timezone.now(),
            consecutive_failures=0
        )
        
        logger.info(f"Registered new source: {source.id} - {name}")
        return source
    
    def track_entity_extraction(
        self,
        source: 'NewsSource',
        article_id: str,
        extracted_entities: List[Dict[str, Any]],
        verified_entities: Optional[List[Dict[str, Any]]] = None
    ) -> 'EntityExtraction':
        """
        Track entity extraction accuracy for a source.
        
        Args:
            source: NewsSource instance
            article_id: Article identifier
            extracted_entities: Entities extracted by the system
            verified_entities: Manually verified entities (for training)
            
        Returns:
            EntityExtraction record
        """
        extraction = EntityExtraction.objects.create(
            source=source,
            article_id=article_id,
            extracted_entities=extracted_entities,
            verified_entities=verified_entities or [],
            extraction_timestamp=timezone.now()
        )
        
        # Calculate accuracy if verified entities provided
        if verified_entities:
            accuracy = self._calculate_extraction_accuracy(
                extracted_entities,
                verified_entities
            )
            extraction.accuracy_score = accuracy
            extraction.save()
            
            # Update source accuracy
            self._update_source_accuracy(source, 'entity', accuracy)
        
        return extraction
    
    def _calculate_extraction_accuracy(
        self,
        extracted: List[Dict[str, Any]],
        verified: List[Dict[str, Any]]
    ) -> float:
        """
        Calculate accuracy between extracted and verified entities.
        """
        if not verified:
            return 0.0
        
        # Convert to sets for comparison
        extracted_set = {
            (e['type'], e['name'].lower())
            for e in extracted
        }
        verified_set = {
            (e['type'], e['name'].lower())
            for e in verified
        }
        
        # Calculate precision and recall
        true_positives = len(extracted_set & verified_set)
        false_positives = len(extracted_set - verified_set)
        false_negatives = len(verified_set - extracted_set)
        
        if true_positives + false_positives == 0:
            precision = 0.0
        else:
            precision = true_positives / (true_positives + false_positives)
        
        if true_positives + false_negatives == 0:
            recall = 0.0
        else:
            recall = true_positives / (true_positives + false_negatives)
        
        # F1 score
        if precision + recall == 0:
            return 0.0
        
        f1_score = 2 * (precision * recall) / (precision + recall)
        return f1_score * 100
    
    def _update_source_accuracy(
        self,
        source: 'NewsSource',
        accuracy_type: str,
        new_score: float
    ):
        """
        Update source accuracy with exponential moving average.
        """
        accuracy = source.accuracy
        alpha = 0.1  # Smoothing factor
        
        if accuracy_type == 'entity':
            current = accuracy.entity_accuracy
            accuracy.entity_accuracy = (alpha * new_score) + ((1 - alpha) * current)
            accuracy.total_entities += 1
        elif accuracy_type == 'sentiment':
            current = accuracy.sentiment_accuracy
            accuracy.sentiment_accuracy = (alpha * new_score) + ((1 - alpha) * current)
        elif accuracy_type == 'classification':
            current = accuracy.classification_accuracy
            accuracy.classification_accuracy = (alpha * new_score) + ((1 - alpha) * current)
        
        accuracy.last_updated = timezone.now()
        accuracy.save()
        
        # Update source quality score
        self._update_quality_score(source)
    
    def _update_quality_score(self, source: 'NewsSource'):
        """
        Update overall quality score for a source.
        """
        accuracy = source.accuracy
        health = source.health
        
        # Weight components
        weights = {
            'entity_accuracy': 0.3,
            'sentiment_accuracy': 0.2,
            'classification_accuracy': 0.2,
            'uptime': 0.2,
            'freshness': 0.1
        }
        
        # Calculate freshness score (how recent the content is)
        if health.last_successful_crawl:
            hours_since_crawl = (
                timezone.now() - health.last_successful_crawl
            ).total_seconds() / 3600
            freshness_score = max(0, 100 - (hours_since_crawl * 2))
        else:
            freshness_score = 0
        
        # Calculate weighted score
        quality_score = (
            weights['entity_accuracy'] * accuracy.entity_accuracy +
            weights['sentiment_accuracy'] * accuracy.sentiment_accuracy +
            weights['classification_accuracy'] * accuracy.classification_accuracy +
            weights['uptime'] * health.uptime_percentage +
            weights['freshness'] * freshness_score
        )
        
        source.quality_score = round(quality_score, 2)
        source.save(update_fields=['quality_score'])
    
    def update_source_health(
        self,
        source: 'NewsSource',
        crawl_success: bool,
        response_time: Optional[float] = None,
        error_message: Optional[str] = None
    ):
        """
        Update source health metrics.
        
        Args:
            source: NewsSource instance
            crawl_success: Whether the crawl succeeded
            response_time: Response time in seconds
            error_message: Error message if failed
        """
        health = source.health
        
        if crawl_success:
            health.last_successful_crawl = timezone.now()
            health.consecutive_failures = 0
            health.status = 'HEALTHY'
            
            # Update response time average
            if response_time and health.average_response_time:
                health.average_response_time = (
                    0.9 * health.average_response_time + 0.1 * response_time
                )
            else:
                health.average_response_time = response_time
        else:
            health.consecutive_failures += 1
            health.last_error = error_message or "Unknown error"
            health.last_error_time = timezone.now()
            
            # Update status based on failures
            if health.consecutive_failures >= 10:
                health.status = 'FAILED'
            elif health.consecutive_failures >= 5:
                health.status = 'DEGRADED'
            else:
                health.status = 'WARNING'
        
        # Update uptime percentage
        total_checks = health.total_checks + 1
        successful_checks = health.successful_checks + (1 if crawl_success else 0)
        health.uptime_percentage = (successful_checks / total_checks) * 100
        health.total_checks = total_checks
        health.successful_checks = successful_checks
        
        health.save()
        
        # Send alert if source is failing
        if health.status in ['DEGRADED', 'FAILED']:
            self._send_source_alert(source, health)
    
    def _send_source_alert(self, source: 'NewsSource', health: 'SourceHealth'):
        """
        Send alert for failing source.
        """
        # Check if alert was recently sent
        cache_key = f"source_alert_{source.id}"
        if cache.get(cache_key):
            return
        
        # Send notification
        self.notification_service.send_admin_notification(
            notification_type='source_health_alert',
            context={
                'source_name': source.name,
                'source_id': str(source.id),
                'status': health.status,
                'consecutive_failures': health.consecutive_failures,
                'last_error': health.last_error
            }
        )
        
        # Set cache to prevent spam (1 hour)
        cache.set(cache_key, True, timeout=3600)
    
    def get_source_catalogue(
        self,
        filters: Optional[Dict[str, Any]] = None,
        order_by: str = '-quality_score'
    ) -> List[Dict[str, Any]]:
        """
        Get the source catalogue with filtering and sorting.
        
        Args:
            filters: Optional filters
            order_by: Sort field
            
        Returns:
            List of source data
        """
        queryset = NewsSource.objects.select_related(
            'accuracy', 'health'
        ).prefetch_related('categories')
        
        # Apply filters
        if filters:
            if 'source_type' in filters:
                queryset = queryset.filter(source_type=filters['source_type'])
            if 'language' in filters:
                queryset = queryset.filter(language=filters['language'])
            if 'country' in filters:
                queryset = queryset.filter(country=filters['country'])
            if 'is_active' in filters:
                queryset = queryset.filter(is_active=filters['is_active'])
            if 'min_quality_score' in filters:
                queryset = queryset.filter(
                    quality_score__gte=filters['min_quality_score']
                )
            if 'categories' in filters:
                queryset = queryset.filter(
                    categories__slug__in=filters['categories']
                ).distinct()
        
        # Order results
        queryset = queryset.order_by(order_by)
        
        # Build response
        catalogue = []
        for source in queryset:
            catalogue.append({
                'id': str(source.id),
                'name': source.name,
                'url': source.url,
                'source_type': source.source_type,
                'language': source.language,
                'country': source.country,
                'categories': [cat.name for cat in source.categories.all()],
                'tags': source.tags,
                'quality_score': source.quality_score,
                'is_active': source.is_active,
                'accuracy': {
                    'entity': source.accuracy.entity_accuracy,
                    'sentiment': source.accuracy.sentiment_accuracy,
                    'classification': source.accuracy.classification_accuracy,
                    'total_articles': source.accuracy.total_articles,
                    'total_entities': source.accuracy.total_entities
                },
                'health': {
                    'status': source.health.status,
                    'uptime': source.health.uptime_percentage,
                    'last_crawl': source.health.last_successful_crawl,
                    'response_time': source.health.average_response_time
                },
                'crawl_frequency': source.crawl_frequency,
                'last_updated': source.updated_at
            })
        
        return catalogue
    
    def get_accuracy_dashboard(
        self,
        time_range: str = '7d',
        group_by: str = 'source'
    ) -> Dict[str, Any]:
        """
        Get accuracy dashboard data.
        
        Args:
            time_range: Time range (1d, 7d, 30d, etc.)
            group_by: Grouping (source, category, type)
            
        Returns:
            Dashboard data
        """
        # Parse time range
        if time_range.endswith('d'):
            days = int(time_range[:-1])
            start_date = timezone.now() - timedelta(days=days)
        else:
            start_date = timezone.now() - timedelta(days=7)
        
        # Get recent extractions
        extractions = EntityExtraction.objects.filter(
            extraction_timestamp__gte=start_date,
            accuracy_score__isnull=False
        ).select_related('source')
        
        # Build dashboard data
        dashboard = {
            'time_range': time_range,
            'start_date': start_date.isoformat(),
            'end_date': timezone.now().isoformat(),
            'overall_metrics': self._calculate_overall_metrics(extractions),
            'accuracy_trends': self._calculate_accuracy_trends(extractions),
            'top_performers': self._get_top_performing_sources(),
            'low_performers': self._get_low_performing_sources(),
            'entity_distribution': self._calculate_entity_distribution(extractions),
            'error_analysis': self._analyze_extraction_errors(extractions)
        }
        
        if group_by == 'category':
            dashboard['category_breakdown'] = self._calculate_category_breakdown()
        elif group_by == 'type':
            dashboard['type_breakdown'] = self._calculate_type_breakdown()
        else:
            dashboard['source_breakdown'] = self._calculate_source_breakdown()
        
        return dashboard
    
    def _calculate_overall_metrics(
        self,
        extractions: models.QuerySet
    ) -> Dict[str, Any]:
        """
        Calculate overall accuracy metrics.
        """
        aggregates = extractions.aggregate(
            avg_accuracy=Avg('accuracy_score'),
            total_extractions=Count('id'),
            total_entities=Sum('entity_count')
        )
        
        # Get active sources count
        active_sources = NewsSource.objects.filter(
            is_active=True
        ).count()
        
        return {
            'average_accuracy': round(aggregates['avg_accuracy'] or 0, 2),
            'total_extractions': aggregates['total_extractions'],
            'total_entities': aggregates['total_entities'] or 0,
            'active_sources': active_sources,
            'extraction_rate': round(
                (aggregates['total_extractions'] / active_sources) if active_sources > 0 else 0,
                2
            )
        }
    
    def _calculate_accuracy_trends(
        self,
        extractions: models.QuerySet
    ) -> List[Dict[str, Any]]:
        """
        Calculate accuracy trends over time.
        """
        # Group by day
        from django.db.models.functions import TruncDay
        
        trends = extractions.annotate(
            day=TruncDay('extraction_timestamp')
        ).values('day').annotate(
            avg_accuracy=Avg('accuracy_score'),
            extraction_count=Count('id')
        ).order_by('day')
        
        return [
            {
                'date': trend['day'].isoformat(),
                'accuracy': round(trend['avg_accuracy'], 2),
                'extractions': trend['extraction_count']
            }
            for trend in trends
        ]
    
    def _get_top_performing_sources(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get top performing sources by quality score.
        """
        sources = NewsSource.objects.filter(
            is_active=True,
            quality_score__gt=0
        ).select_related('accuracy').order_by('-quality_score')[:limit]
        
        return [
            {
                'id': str(source.id),
                'name': source.name,
                'quality_score': source.quality_score,
                'entity_accuracy': source.accuracy.entity_accuracy,
                'uptime': source.health.uptime_percentage
            }
            for source in sources
        ]
    
    def _get_low_performing_sources(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get low performing sources that need attention.
        """
        sources = NewsSource.objects.filter(
            is_active=True
        ).select_related('accuracy', 'health').filter(
            Q(quality_score__lt=50) | Q(health__status__in=['DEGRADED', 'FAILED'])
        ).order_by('quality_score')[:limit]
        
        return [
            {
                'id': str(source.id),
                'name': source.name,
                'quality_score': source.quality_score,
                'entity_accuracy': source.accuracy.entity_accuracy,
                'health_status': source.health.status,
                'issues': self._identify_source_issues(source)
            }
            for source in sources
        ]
    
    def _identify_source_issues(self, source: 'NewsSource') -> List[str]:
        """
        Identify specific issues with a source.
        """
        issues = []
        
        if source.accuracy.entity_accuracy < 70:
            issues.append("Low entity extraction accuracy")
        if source.accuracy.sentiment_accuracy < 70:
            issues.append("Low sentiment analysis accuracy")
        if source.health.uptime_percentage < 90:
            issues.append("Poor uptime")
        if source.health.status in ['DEGRADED', 'FAILED']:
            issues.append(f"Health status: {source.health.status}")
        if source.health.average_response_time and source.health.average_response_time > 5:
            issues.append("Slow response time")
        
        return issues
    
    def _calculate_entity_distribution(
        self,
        extractions: models.QuerySet
    ) -> Dict[str, int]:
        """
        Calculate distribution of entity types.
        """
        distribution = defaultdict(int)
        
        for extraction in extractions[:1000]:  # Sample for performance
            for entity in extraction.extracted_entities:
                entity_type = entity.get('type', 'UNKNOWN')
                distribution[entity_type] += 1
        
        return dict(distribution)
    
    def _analyze_extraction_errors(
        self,
        extractions: models.QuerySet
    ) -> List[Dict[str, Any]]:
        """
        Analyze common extraction errors.
        """
        error_patterns = defaultdict(int)
        error_examples = defaultdict(list)
        
        for extraction in extractions.filter(accuracy_score__lt=80)[:500]:
            if not extraction.verified_entities:
                continue
            
            # Find missed entities
            extracted_names = {
                e['name'].lower() for e in extraction.extracted_entities
            }
            verified_names = {
                e['name'].lower() for e in extraction.verified_entities
            }
            
            missed = verified_names - extracted_names
            false_positives = extracted_names - verified_names
            
            if missed:
                error_patterns['missed_entities'] += len(missed)
                if len(error_examples['missed_entities']) < 5:
                    error_examples['missed_entities'].extend(list(missed)[:2])
            
            if false_positives:
                error_patterns['false_positives'] += len(false_positives)
                if len(error_examples['false_positives']) < 5:
                    error_examples['false_positives'].extend(list(false_positives)[:2])
        
        return [
            {
                'error_type': error_type,
                'count': count,
                'examples': error_examples.get(error_type, [])
            }
            for error_type, count in error_patterns.items()
        ]
    
    def _calculate_category_breakdown(self) -> List[Dict[str, Any]]:
        """
        Calculate accuracy breakdown by category.
        """
        categories = SourceCategory.objects.annotate(
            source_count=Count('sources'),
            avg_quality=Avg('sources__quality_score'),
            avg_entity_accuracy=Avg('sources__accuracy__entity_accuracy')
        ).filter(source_count__gt=0)
        
        return [
            {
                'category': cat.name,
                'source_count': cat.source_count,
                'average_quality': round(cat.avg_quality or 0, 2),
                'average_accuracy': round(cat.avg_entity_accuracy or 0, 2)
            }
            for cat in categories
        ]
    
    def _calculate_type_breakdown(self) -> List[Dict[str, Any]]:
        """
        Calculate accuracy breakdown by source type.
        """
        type_stats = NewsSource.objects.values('source_type').annotate(
            count=Count('id'),
            avg_quality=Avg('quality_score'),
            avg_accuracy=Avg('accuracy__entity_accuracy')
        )
        
        return [
            {
                'type': stat['source_type'],
                'count': stat['count'],
                'average_quality': round(stat['avg_quality'] or 0, 2),
                'average_accuracy': round(stat['avg_accuracy'] or 0, 2)
            }
            for stat in type_stats
        ]
    
    def _calculate_source_breakdown(self) -> List[Dict[str, Any]]:
        """
        Calculate detailed source breakdown.
        """
        sources = NewsSource.objects.filter(
            is_active=True
        ).select_related('accuracy', 'health').order_by('-quality_score')[:50]
        
        return [
            {
                'id': str(source.id),
                'name': source.name,
                'quality_score': source.quality_score,
                'entity_accuracy': source.accuracy.entity_accuracy,
                'total_articles': source.accuracy.total_articles,
                'health_status': source.health.status,
                'last_crawl': source.health.last_successful_crawl
            }
            for source in sources
        ]
    
    def export_catalogue(
        self,
        format: str = 'json',
        include_inactive: bool = False
    ) -> str:
        """
        Export the source catalogue.
        
        Args:
            format: Export format (json, csv, excel)
            include_inactive: Include inactive sources
            
        Returns:
            File path or URL
        """
        filters = {} if include_inactive else {'is_active': True}
        catalogue = self.get_source_catalogue(filters=filters)
        
        if format == 'json':
            return self._export_json(catalogue)
        elif format == 'csv':
            return self._export_csv(catalogue)
        elif format == 'excel':
            return self._export_excel(catalogue)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _export_json(self, data: List[Dict[str, Any]]) -> str:
        """
        Export data as JSON.
        """
        file_path = f"/tmp/source_catalogue_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(file_path, 'w') as f:
            json.dump({
                'generated_at': timezone.now().isoformat(),
                'source_count': len(data),
                'sources': data
            }, f, indent=2, default=str)
        
        return file_path
    
    def _export_csv(self, data: List[Dict[str, Any]]) -> str:
        """
        Export data as CSV.
        """
        import csv
        
        file_path = f"/tmp/source_catalogue_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        if not data:
            return file_path
        
        # Flatten nested data
        flattened = []
        for source in data:
            flat = {
                'id': source['id'],
                'name': source['name'],
                'url': source['url'],
                'type': source['source_type'],
                'language': source['language'],
                'country': source['country'],
                'categories': ', '.join(source['categories']),
                'quality_score': source['quality_score'],
                'entity_accuracy': source['accuracy']['entity'],
                'uptime': source['health']['uptime'],
                'status': source['health']['status']
            }
            flattened.append(flat)
        
        # Write CSV
        with open(file_path, 'w', newline='') as f:
            if flattened:
                writer = csv.DictWriter(f, fieldnames=flattened[0].keys())
                writer.writeheader()
                writer.writerows(flattened)
        
        return file_path
    
    def _export_excel(self, data: List[Dict[str, Any]]) -> str:
        """
        Export data as Excel.
        """
        import pandas as pd
        
        file_path = f"/tmp/source_catalogue_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # Convert to DataFrame
        df_data = []
        for source in data:
            df_data.append({
                'ID': source['id'],
                'Name': source['name'],
                'URL': source['url'],
                'Type': source['source_type'],
                'Language': source['language'],
                'Country': source['country'],
                'Categories': ', '.join(source['categories']),
                'Quality Score': source['quality_score'],
                'Entity Accuracy': source['accuracy']['entity'],
                'Sentiment Accuracy': source['accuracy']['sentiment'],
                'Classification Accuracy': source['accuracy']['classification'],
                'Total Articles': source['accuracy']['total_articles'],
                'Uptime %': source['health']['uptime'],
                'Health Status': source['health']['status'],
                'Last Crawl': source['health']['last_crawl']
            })
        
        df = pd.DataFrame(df_data)
        
        # Write to Excel with formatting
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Source Catalogue', index=False)
            
            # Add summary sheet
            summary_data = {
                'Metric': [
                    'Total Sources',
                    'Active Sources',
                    'Average Quality Score',
                    'Average Entity Accuracy',
                    'Sources with >90% Uptime'
                ],
                'Value': [
                    len(data),
                    sum(1 for s in data if s['is_active']),
                    round(sum(s['quality_score'] for s in data) / len(data), 2) if data else 0,
                    round(sum(s['accuracy']['entity'] for s in data) / len(data), 2) if data else 0,
                    sum(1 for s in data if s['health']['uptime'] > 90)
                ]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
        
        return file_path


@shared_task
def update_source_metrics():
    """
    Periodic task to update source metrics and quality scores.
    """
    service = SourceCatalogueService()
    
    # Update quality scores for all active sources
    active_sources = NewsSource.objects.filter(is_active=True)
    
    for source in active_sources:
        service._update_quality_score(source)
    
    logger.info(f"Updated metrics for {active_sources.count()} sources")


@shared_task
def generate_accuracy_report():
    """
    Generate daily accuracy report.
    """
    service = SourceCatalogueService()
    
    # Get dashboard data
    dashboard = service.get_accuracy_dashboard(time_range='1d')
    
    # Send to administrators
    service.notification_service.send_admin_notification(
        notification_type='daily_accuracy_report',
        context={
            'date': timezone.now().date().isoformat(),
            'overall_accuracy': dashboard['overall_metrics']['average_accuracy'],
            'total_extractions': dashboard['overall_metrics']['total_extractions'],
            'top_performer': dashboard['top_performers'][0] if dashboard['top_performers'] else None,
            'issues_count': len(dashboard['low_performers'])
        }
    )
    
    logger.info("Generated daily accuracy report")


@shared_task
def check_source_health():
    """
    Check health of all active sources.
    """
    service = SourceCatalogueService()
    
    sources = NewsSource.objects.filter(is_active=True)
    
    for source in sources:
        try:
            # Simple health check - try to access the source
            start_time = timezone.now()
            response = requests.head(source.url, timeout=10)
            response_time = (timezone.now() - start_time).total_seconds()
            
            success = response.status_code < 400
            error_message = None if success else f"HTTP {response.status_code}"
            
        except Exception as e:
            success = False
            response_time = None
            error_message = str(e)
        
        service.update_source_health(
            source=source,
            crawl_success=success,
            response_time=response_time,
            error_message=error_message
        )
    
    logger.info(f"Checked health for {sources.count()} sources")