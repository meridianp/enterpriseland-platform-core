"""
Investment Module API Serializers

DRF serializers for investment module models and services.
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from business_modules.investment.models import (
    TargetCompany, Lead, Deal, Assessment,
    DealTeamMember, DealMilestone, LeadActivity
)

User = get_user_model()


# Market Intelligence Serializers

class TargetCompanySerializer(serializers.ModelSerializer):
    """Target company serializer."""
    
    score = serializers.FloatField(read_only=True)
    source_article_count = serializers.IntegerField(
        source='source_articles.count',
        read_only=True
    )
    
    class Meta:
        model = TargetCompany
        fields = [
            'id', 'name', 'sector', 'description', 'website',
            'score', 'score_components', 'discovered_date',
            'source_article_count', 'metadata'
        ]
        read_only_fields = ['discovered_date', 'score_components']


class NewsDiscoverySerializer(serializers.Serializer):
    """News discovery request serializer."""
    
    query_templates = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of query template names to use"
    )


class MarketTrendsSerializer(serializers.Serializer):
    """Market trends request serializer."""
    
    sector = serializers.CharField(required=False)
    period = serializers.ChoiceField(
        choices=['day', 'week', 'month', 'year'],
        default='month'
    )


# Lead Management Serializers

class LeadSerializer(serializers.ModelSerializer):
    """Lead serializer."""
    
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False
    )
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True
    )
    activity_count = serializers.IntegerField(
        source='activities.count',
        read_only=True
    )
    
    class Meta:
        model = Lead
        fields = [
            'id', 'company_name', 'contact_name', 'contact_email',
            'contact_phone', 'source', 'sector', 'description',
            'score', 'status', 'assigned_to', 'assigned_to_name',
            'activity_count', 'created_date', 'qualified_date',
            'metadata'
        ]
        read_only_fields = [
            'score', 'status', 'created_date', 'qualified_date'
        ]
    
    def validate(self, data):
        """Validate lead data."""
        if not data.get('contact_email') and not data.get('contact_phone'):
            raise serializers.ValidationError(
                "At least one contact method (email or phone) is required"
            )
        return data


class LeadActivitySerializer(serializers.ModelSerializer):
    """Lead activity serializer."""
    
    user_name = serializers.CharField(
        source='user.get_full_name',
        read_only=True
    )
    
    class Meta:
        model = LeadActivity
        fields = [
            'id', 'activity_type', 'description', 'user',
            'user_name', 'created_date', 'metadata'
        ]
        read_only_fields = ['created_date']


class LeadAssignmentSerializer(serializers.Serializer):
    """Lead assignment request serializer."""
    
    user_id = serializers.UUIDField(required=False)
    auto_assign = serializers.BooleanField(default=False)


class LeadScoringSerializer(serializers.Serializer):
    """Lead scoring request serializer."""
    
    model_id = serializers.UUIDField(required=False)
    force_rescore = serializers.BooleanField(default=False)


# Deal Workspace Serializers

class DealTeamMemberSerializer(serializers.ModelSerializer):
    """Deal team member serializer."""
    
    user_name = serializers.CharField(
        source='user.get_full_name',
        read_only=True
    )
    user_email = serializers.EmailField(
        source='user.email',
        read_only=True
    )
    
    class Meta:
        model = DealTeamMember
        fields = [
            'id', 'user', 'user_name', 'user_email', 'role',
            'can_edit', 'can_approve', 'joined_date'
        ]
        read_only_fields = ['joined_date']


class DealMilestoneSerializer(serializers.ModelSerializer):
    """Deal milestone serializer."""
    
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True,
        allow_null=True
    )
    dependency_ids = serializers.PrimaryKeyRelatedField(
        source='dependencies',
        many=True,
        queryset=DealMilestone.objects.all(),
        required=False
    )
    
    class Meta:
        model = DealMilestone
        fields = [
            'id', 'name', 'description', 'stage', 'is_blocking',
            'target_date', 'completed_date', 'assigned_to',
            'assigned_to_name', 'order', 'dependency_ids'
        ]
        read_only_fields = ['completed_date']


class DealSerializer(serializers.ModelSerializer):
    """Deal serializer."""
    
    team_members = DealTeamMemberSerializer(many=True, read_only=True)
    milestones = DealMilestoneSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True
    )
    deal_type_name = serializers.CharField(
        source='deal_type.name',
        read_only=True
    )
    
    class Meta:
        model = Deal
        fields = [
            'id', 'title', 'deal_type', 'deal_type_name', 'lead',
            'partner', 'description', 'current_stage', 'status',
            'deal_size', 'currency', 'irr', 'target_close_date',
            'team_members', 'milestones', 'created_by',
            'created_by_name', 'created_date', 'metadata'
        ]
        read_only_fields = [
            'current_stage', 'status', 'created_date'
        ]


class DealCreateSerializer(serializers.ModelSerializer):
    """Deal creation serializer."""
    
    team_members = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="List of team members to add"
    )
    
    class Meta:
        model = Deal
        fields = [
            'title', 'deal_type', 'lead', 'partner', 'description',
            'deal_size', 'currency', 'target_close_date',
            'team_members', 'metadata'
        ]
    
    def validate_team_members(self, value):
        """Validate team members."""
        for member in value:
            if 'user_id' not in member:
                raise serializers.ValidationError(
                    "Each team member must have user_id"
                )
            if not User.objects.filter(id=member['user_id']).exists():
                raise serializers.ValidationError(
                    f"User {member['user_id']} not found"
                )
        return value


class DealTransitionSerializer(serializers.Serializer):
    """Deal stage transition serializer."""
    
    target_stage = serializers.CharField()
    reason = serializers.CharField(required=False)


class ICPackGenerationSerializer(serializers.Serializer):
    """IC pack generation request serializer."""
    
    template = serializers.CharField(required=False)
    include_sections = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )


# Assessment Serializers

class AssessmentSerializer(serializers.ModelSerializer):
    """Assessment serializer."""
    
    partner_name = serializers.CharField(
        source='partner.name',
        read_only=True
    )
    template_name = serializers.CharField(
        source='template.name',
        read_only=True
    )
    section_count = serializers.IntegerField(
        source='sections.count',
        read_only=True
    )
    
    class Meta:
        model = Assessment
        fields = [
            'id', 'title', 'partner', 'partner_name', 'template',
            'template_name', 'status', 'overall_score',
            'section_scores', 'section_count', 'submitted_date',
            'approved_date', 'created_date', 'metadata'
        ]
        read_only_fields = [
            'overall_score', 'section_scores', 'submitted_date',
            'approved_date', 'created_date'
        ]


class AssessmentCreateSerializer(serializers.Serializer):
    """Assessment creation serializer."""
    
    partner_id = serializers.UUIDField()
    template = serializers.CharField()


class AssessmentSubmitSerializer(serializers.Serializer):
    """Assessment submission serializer."""
    
    sections = serializers.DictField(
        child=serializers.DictField(),
        help_text="Responses organized by section ID"
    )
    submitted_by_id = serializers.UUIDField()


class AssessmentReviewSerializer(serializers.Serializer):
    """Assessment review serializer."""
    
    decision = serializers.ChoiceField(
        choices=['approve', 'reject', 'request_changes']
    )
    comments = serializers.CharField()


class ReportGenerationSerializer(serializers.Serializer):
    """Report generation request serializer."""
    
    format = serializers.ChoiceField(
        choices=['pdf', 'docx', 'html'],
        default='pdf'
    )
    include_benchmarks = serializers.BooleanField(default=True)
    include_responses = serializers.BooleanField(default=True)


# Analytics Serializers

class PipelineAnalyticsSerializer(serializers.Serializer):
    """Pipeline analytics request serializer."""
    
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    sector = serializers.CharField(required=False)
    assigned_to_id = serializers.UUIDField(required=False)


class BenchmarkSerializer(serializers.Serializer):
    """Benchmark request serializer."""
    
    sector = serializers.CharField()
    assessment_type = serializers.CharField()