"""
Source Catalogue Serializers

Serializers for market intelligence source catalogue API.
"""
from rest_framework import serializers
from ..models import (
    NewsSource, SourceCategory, SourceAccuracy,
    SourceHealth, EntityExtraction, SourceAlert,
    SourceMetrics
)


class SourceCategorySerializer(serializers.ModelSerializer):
    """Serializer for source categories."""
    
    source_count = serializers.IntegerField(read_only=True)
    parent_name = serializers.CharField(
        source='parent.name',
        read_only=True
    )
    
    class Meta:
        model = SourceCategory
        fields = [
            'id', 'name', 'slug', 'description',
            'parent', 'parent_name', 'is_active',
            'source_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SourceAccuracySerializer(serializers.ModelSerializer):
    """Serializer for source accuracy metrics."""
    
    overall_accuracy = serializers.SerializerMethodField()
    
    class Meta:
        model = SourceAccuracy
        fields = [
            'entity_accuracy', 'sentiment_accuracy',
            'classification_accuracy', 'relevance_score',
            'overall_accuracy', 'total_articles',
            'total_entities', 'verified_samples',
            'last_accuracy_check', 'accuracy_trend',
            'updated_at'
        ]
        read_only_fields = ['updated_at']
    
    def get_overall_accuracy(self, obj):
        """Calculate weighted overall accuracy."""
        weights = {
            'entity': 0.4,
            'sentiment': 0.3,
            'classification': 0.3
        }
        
        return round(
            weights['entity'] * obj.entity_accuracy +
            weights['sentiment'] * obj.sentiment_accuracy +
            weights['classification'] * obj.classification_accuracy,
            2
        )


class SourceHealthSerializer(serializers.ModelSerializer):
    """Serializer for source health status."""
    
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    time_since_last_crawl = serializers.SerializerMethodField()
    
    class Meta:
        model = SourceHealth
        fields = [
            'status', 'status_display', 'uptime_percentage',
            'last_successful_crawl', 'time_since_last_crawl',
            'consecutive_failures', 'total_checks',
            'successful_checks', 'average_response_time',
            'last_response_time', 'last_error',
            'last_error_time', 'error_count', 'updated_at'
        ]
        read_only_fields = ['updated_at']
    
    def get_time_since_last_crawl(self, obj):
        """Calculate time since last successful crawl."""
        if not obj.last_successful_crawl:
            return None
        
        from django.utils import timezone
        delta = timezone.now() - obj.last_successful_crawl
        
        if delta.days > 0:
            return f"{delta.days} days ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600} hours ago"
        else:
            return f"{delta.seconds // 60} minutes ago"


class NewsSourceSerializer(serializers.ModelSerializer):
    """Comprehensive serializer for news sources."""
    
    accuracy = SourceAccuracySerializer(read_only=True)
    health = SourceHealthSerializer(read_only=True)
    categories = SourceCategorySerializer(many=True, read_only=True)
    category_ids = serializers.PrimaryKeyRelatedField(
        queryset=SourceCategory.objects.all(),
        many=True,
        write_only=True,
        source='categories'
    )
    
    class Meta:
        model = NewsSource
        fields = [
            'id', 'name', 'url', 'feed_url', 'source_type',
            'language', 'country', 'timezone', 'categories',
            'category_ids', 'tags', 'is_active',
            'crawl_frequency', 'configuration',
            'quality_score', 'reliability_rating',
            'discovered_at', 'last_crawled', 'article_count',
            'accuracy', 'health', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'quality_score', 'discovered_at',
            'last_crawled', 'article_count',
            'created_at', 'updated_at'
        ]
    
    def validate_crawl_frequency(self, value):
        """Validate crawl frequency is reasonable."""
        if value < 60:
            raise serializers.ValidationError(
                "Crawl frequency must be at least 60 seconds"
            )
        if value > 86400:  # 24 hours
            raise serializers.ValidationError(
                "Crawl frequency cannot exceed 24 hours"
            )
        return value


class NewsSourceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for source listings."""
    
    categories = serializers.StringRelatedField(many=True)
    health_status = serializers.CharField(
        source='health.status',
        read_only=True
    )
    entity_accuracy = serializers.FloatField(
        source='accuracy.entity_accuracy',
        read_only=True
    )
    
    class Meta:
        model = NewsSource
        fields = [
            'id', 'name', 'url', 'source_type',
            'language', 'country', 'categories',
            'quality_score', 'is_active',
            'health_status', 'entity_accuracy',
            'last_crawled', 'article_count'
        ]


class EntityExtractionSerializer(serializers.ModelSerializer):
    """Serializer for entity extraction records."""
    
    source_name = serializers.CharField(
        source='source.name',
        read_only=True
    )
    f1_score = serializers.SerializerMethodField()
    
    class Meta:
        model = EntityExtraction
        fields = [
            'id', 'source', 'source_name', 'article_id',
            'extracted_entities', 'verified_entities',
            'entity_count', 'accuracy_score',
            'precision_score', 'recall_score', 'f1_score',
            'extraction_timestamp', 'processing_time'
        ]
        read_only_fields = [
            'id', 'entity_count', 'accuracy_score',
            'precision_score', 'recall_score',
            'extraction_timestamp'
        ]
    
    def get_f1_score(self, obj):
        """Calculate F1 score from precision and recall."""
        if not obj.precision_score or not obj.recall_score:
            return None
        
        if obj.precision_score + obj.recall_score == 0:
            return 0
        
        return round(
            2 * (obj.precision_score * obj.recall_score) /
            (obj.precision_score + obj.recall_score),
            2
        )


class SourceAlertSerializer(serializers.ModelSerializer):
    """Serializer for source alerts."""
    
    source_name = serializers.CharField(
        source='source.name',
        read_only=True
    )
    alert_type_display = serializers.CharField(
        source='get_alert_type_display',
        read_only=True
    )
    severity_display = serializers.CharField(
        source='get_severity_display',
        read_only=True
    )
    time_since_created = serializers.SerializerMethodField()
    
    class Meta:
        model = SourceAlert
        fields = [
            'id', 'source', 'source_name', 'alert_type',
            'alert_type_display', 'severity', 'severity_display',
            'message', 'details', 'is_resolved', 'resolved_at',
            'resolved_by', 'resolution_notes',
            'notifications_sent', 'last_notification',
            'created_at', 'time_since_created'
        ]
        read_only_fields = [
            'id', 'notifications_sent', 'last_notification',
            'created_at'
        ]
    
    def get_time_since_created(self, obj):
        """Calculate time since alert was created."""
        from django.utils import timezone
        delta = timezone.now() - obj.created_at
        
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600}h ago"
        else:
            return f"{delta.seconds // 60}m ago"


class SourceMetricsSerializer(serializers.ModelSerializer):
    """Serializer for daily source metrics."""
    
    source_name = serializers.CharField(
        source='source.name',
        read_only=True
    )
    
    class Meta:
        model = SourceMetrics
        fields = [
            'source', 'source_name', 'date',
            'articles_crawled', 'entities_extracted',
            'unique_entities', 'avg_entity_accuracy',
            'avg_sentiment_accuracy', 'avg_response_time',
            'uptime_percentage', 'error_count',
            'entity_distribution'
        ]


class SourceAccuracyDashboardSerializer(serializers.Serializer):
    """Serializer for accuracy dashboard data."""
    
    time_range = serializers.CharField()
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    overall_metrics = serializers.DictField()
    accuracy_trends = serializers.ListField(
        child=serializers.DictField()
    )
    top_performers = serializers.ListField(
        child=serializers.DictField()
    )
    low_performers = serializers.ListField(
        child=serializers.DictField()
    )
    entity_distribution = serializers.DictField()
    error_analysis = serializers.ListField(
        child=serializers.DictField()
    )


class BulkSourceRegistrationSerializer(serializers.Serializer):
    """Serializer for bulk source registration."""
    
    sources = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=100
    )


class SourceExportSerializer(serializers.Serializer):
    """Serializer for source export requests."""
    
    format = serializers.ChoiceField(
        choices=['json', 'csv', 'excel'],
        default='json'
    )
    include_inactive = serializers.BooleanField(default=False)
    min_quality_score = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100
    )
    categories = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )