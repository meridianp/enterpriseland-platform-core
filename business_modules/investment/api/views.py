"""
Investment Module API Views

RESTful API endpoints using Django REST Framework.
"""

import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone

from platform_core.security.permissions import IsGroupMember
from platform_core.api.pagination import StandardResultsSetPagination
from platform_core.api.filters import GroupFilterBackend

from business_modules.investment.models import (
    TargetCompany, Lead, Deal, Assessment
)
from business_modules.investment.services import (
    MarketIntelligenceServiceImpl,
    LeadManagementServiceImpl,
    DealWorkspaceServiceImpl,
    AssessmentServiceImpl
)
from .serializers import (
    # Market Intelligence
    TargetCompanySerializer, NewsDiscoverySerializer, MarketTrendsSerializer,
    # Lead Management
    LeadSerializer, LeadActivitySerializer, LeadAssignmentSerializer,
    LeadScoringSerializer, PipelineAnalyticsSerializer,
    # Deal Workspace
    DealSerializer, DealCreateSerializer, DealTransitionSerializer,
    DealTeamMemberSerializer, DealMilestoneSerializer, ICPackGenerationSerializer,
    # Assessment
    AssessmentSerializer, AssessmentCreateSerializer, AssessmentSubmitSerializer,
    AssessmentReviewSerializer, ReportGenerationSerializer, BenchmarkSerializer
)

logger = logging.getLogger(__name__)


class MarketIntelligenceViewSet(viewsets.ModelViewSet):
    """
    Market Intelligence API endpoints.
    
    Provides news discovery, target identification, and market analytics.
    """
    
    queryset = TargetCompany.objects.all()
    serializer_class = TargetCompanySerializer
    permission_classes = [permissions.IsAuthenticated, IsGroupMember]
    filter_backends = [GroupFilterBackend]
    pagination_class = StandardResultsSetPagination
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = MarketIntelligenceServiceImpl()
    
    @action(detail=False, methods=['post'])
    def discover_news(self, request):
        """
        Discover news articles based on query templates.
        
        POST /api/investment/market-intel/discover_news/
        """
        serializer = NewsDiscoverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            articles = self.service.discover_news(
                query_templates=serializer.validated_data.get('query_templates')
            )
            
            return Response({
                'status': 'success',
                'discovered': len(articles),
                'articles': articles
            })
            
        except Exception as e:
            logger.error(f"Error discovering news: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def identify_targets(self, request):
        """
        Identify target companies from news articles.
        
        POST /api/investment/market-intel/identify_targets/
        """
        articles = request.data.get('articles', [])
        
        if not articles:
            return Response(
                {'error': 'No articles provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            targets = self.service.identify_targets(articles)
            
            return Response({
                'status': 'success',
                'identified': len(targets),
                'targets': targets
            })
            
        except Exception as e:
            logger.error(f"Error identifying targets: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def score(self, request, pk=None):
        """
        Score a target company.
        
        POST /api/investment/market-intel/{id}/score/
        """
        target = self.get_object()
        
        try:
            score = self.service.score_target({'id': str(target.id)})
            
            return Response({
                'status': 'success',
                'score': score,
                'target_id': str(target.id)
            })
            
        except Exception as e:
            logger.error(f"Error scoring target {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def trends(self, request):
        """
        Get market trends and analytics.
        
        GET /api/investment/market-intel/trends/
        """
        serializer = MarketTrendsSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        
        try:
            trends = self.service.get_market_trends(
                sector=serializer.validated_data.get('sector'),
                period=serializer.validated_data.get('period', 'month')
            )
            
            return Response(trends)
            
        except Exception as e:
            logger.error(f"Error getting market trends: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def track_competitor(self, request, pk=None):
        """
        Track competitor activities.
        
        GET /api/investment/market-intel/{id}/track_competitor/
        """
        try:
            tracking_data = self.service.track_competitor(pk)
            return Response(tracking_data)
            
        except Exception as e:
            logger.error(f"Error tracking competitor {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LeadManagementViewSet(viewsets.ModelViewSet):
    """
    Lead Management API endpoints.
    
    Provides lead CRUD, scoring, qualification, and analytics.
    """
    
    queryset = Lead.objects.select_related('assigned_to').prefetch_related('activities')
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated, IsGroupMember]
    filter_backends = [GroupFilterBackend]
    pagination_class = StandardResultsSetPagination
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = LeadManagementServiceImpl()
    
    def create(self, request, *args, **kwargs):
        """Create a new lead with automatic scoring."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Add group and creator info
            lead_data = serializer.validated_data
            lead_data['group_id'] = request.user.group_id
            lead_data['created_by_id'] = request.user.id
            
            result = self.service.create_lead(lead_data)
            
            return Response(result, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating lead: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def score(self, request, pk=None):
        """
        Score or re-score a lead.
        
        POST /api/investment/leads/{id}/score/
        """
        lead = self.get_object()
        serializer = LeadScoringSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            result = self.service.score_lead(
                str(lead.id),
                model_id=serializer.validated_data.get('model_id')
            )
            
            return Response(result)
            
        except Exception as e:
            logger.error(f"Error scoring lead {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def qualify(self, request, pk=None):
        """
        Qualify a lead for follow-up.
        
        POST /api/investment/leads/{id}/qualify/
        """
        lead = self.get_object()
        
        try:
            qualified, reason = self.service.qualify_lead(str(lead.id))
            
            return Response({
                'qualified': qualified,
                'reason': reason,
                'lead_id': str(lead.id)
            })
            
        except Exception as e:
            logger.error(f"Error qualifying lead {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """
        Assign lead to user.
        
        POST /api/investment/leads/{id}/assign/
        """
        lead = self.get_object()
        serializer = LeadAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            result = self.service.assign_lead(
                str(lead.id),
                user_id=serializer.validated_data.get('user_id')
            )
            
            return Response(result)
            
        except Exception as e:
            logger.error(f"Error assigning lead {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def activities(self, request, pk=None):
        """
        Get lead activities.
        
        GET /api/investment/leads/{id}/activities/
        """
        lead = self.get_object()
        activities = lead.activities.select_related('user').order_by('-created_date')
        
        serializer = LeadActivitySerializer(activities, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """
        Get lead pipeline analytics.
        
        GET /api/investment/leads/analytics/
        """
        serializer = PipelineAnalyticsSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        
        try:
            analytics = self.service.get_pipeline_analytics(
                filters=serializer.validated_data
            )
            
            return Response(analytics)
            
        except Exception as e:
            logger.error(f"Error getting pipeline analytics: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def process_overdue(self, request):
        """
        Process overdue leads.
        
        POST /api/investment/leads/process_overdue/
        """
        try:
            processed = self.service.process_overdue_leads()
            
            return Response({
                'status': 'success',
                'processed': len(processed),
                'leads': processed
            })
            
        except Exception as e:
            logger.error(f"Error processing overdue leads: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DealWorkspaceViewSet(viewsets.ModelViewSet):
    """
    Deal Workspace API endpoints.
    
    Provides deal management, workflow transitions, and collaboration.
    """
    
    queryset = Deal.objects.select_related(
        'deal_type', 'lead', 'partner', 'created_by'
    ).prefetch_related(
        'team_members__user', 'milestones'
    )
    serializer_class = DealSerializer
    permission_classes = [permissions.IsAuthenticated, IsGroupMember]
    filter_backends = [GroupFilterBackend]
    pagination_class = StandardResultsSetPagination
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = DealWorkspaceServiceImpl()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return DealCreateSerializer
        return super().get_serializer_class()
    
    def create(self, request, *args, **kwargs):
        """Create a new deal with workflow initialization."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Add group and creator info
            deal_data = serializer.validated_data
            deal_data['group_id'] = request.user.group_id
            deal_data['created_by_id'] = request.user.id
            
            result = self.service.create_deal(deal_data)
            
            return Response(result, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating deal: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def transition(self, request, pk=None):
        """
        Transition deal to new stage.
        
        POST /api/investment/deals/{id}/transition/
        """
        deal = self.get_object()
        serializer = DealTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            success, message = self.service.transition_stage(
                str(deal.id),
                serializer.validated_data['target_stage'],
                str(request.user.id)
            )
            
            if success:
                return Response({
                    'status': 'success',
                    'message': message,
                    'new_stage': deal.current_stage
                })
            else:
                return Response(
                    {'error': message},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error transitioning deal {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def add_team_member(self, request, pk=None):
        """
        Add team member to deal.
        
        POST /api/investment/deals/{id}/add_team_member/
        """
        deal = self.get_object()
        
        try:
            result = self.service.add_team_member(
                str(deal.id),
                request.data.get('user_id'),
                request.data.get('role', 'member')
            )
            
            return Response(result)
            
        except Exception as e:
            logger.error(f"Error adding team member to deal {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def team_members(self, request, pk=None):
        """
        Get deal team members.
        
        GET /api/investment/deals/{id}/team_members/
        """
        deal = self.get_object()
        team_members = deal.team_members.select_related('user')
        
        serializer = DealTeamMemberSerializer(team_members, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get', 'post'])
    def milestones(self, request, pk=None):
        """
        Get or create deal milestones.
        
        GET/POST /api/investment/deals/{id}/milestones/
        """
        deal = self.get_object()
        
        if request.method == 'GET':
            milestones = deal.milestones.select_related('assigned_to').order_by('order')
            serializer = DealMilestoneSerializer(milestones, many=True)
            return Response(serializer.data)
        
        else:  # POST
            serializer = DealMilestoneSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            try:
                result = self.service.create_milestone(
                    str(deal.id),
                    serializer.validated_data
                )
                
                return Response(result, status=status.HTTP_201_CREATED)
                
            except Exception as e:
                logger.error(f"Error creating milestone for deal {pk}: {e}")
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
    
    @action(detail=True, methods=['post'])
    def generate_ic_pack(self, request, pk=None):
        """
        Generate Investment Committee pack.
        
        POST /api/investment/deals/{id}/generate_ic_pack/
        """
        deal = self.get_object()
        serializer = ICPackGenerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            result = self.service.generate_ic_pack(
                str(deal.id),
                template=serializer.validated_data.get('template')
            )
            
            return Response(result)
            
        except Exception as e:
            logger.error(f"Error generating IC pack for deal {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def schedule_meeting(self, request, pk=None):
        """
        Schedule deal-related meeting.
        
        POST /api/investment/deals/{id}/schedule_meeting/
        """
        deal = self.get_object()
        
        meeting_data = request.data.copy()
        meeting_data['organized_by_id'] = str(request.user.id)
        
        try:
            result = self.service.schedule_meeting(str(deal.id), meeting_data)
            
            return Response(result)
            
        except Exception as e:
            logger.error(f"Error scheduling meeting for deal {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AssessmentViewSet(viewsets.ModelViewSet):
    """
    Assessment API endpoints.
    
    Provides assessment management, scoring, and reporting.
    """
    
    queryset = Assessment.objects.select_related(
        'partner', 'template', 'submitted_by', 'approved_by'
    ).prefetch_related('sections')
    serializer_class = AssessmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsGroupMember]
    filter_backends = [GroupFilterBackend]
    pagination_class = StandardResultsSetPagination
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = AssessmentServiceImpl()
    
    @action(detail=False, methods=['post'])
    def create_assessment(self, request):
        """
        Create new assessment from template.
        
        POST /api/investment/assessments/create_assessment/
        """
        serializer = AssessmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            result = self.service.create_assessment(
                serializer.validated_data['partner_id'],
                serializer.validated_data['template']
            )
            
            return Response(result, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating assessment: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """
        Submit assessment for review.
        
        POST /api/investment/assessments/{id}/submit/
        """
        assessment = self.get_object()
        serializer = AssessmentSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            success, message = self.service.submit_assessment(
                str(assessment.id),
                serializer.validated_data
            )
            
            if success:
                return Response({
                    'status': 'success',
                    'message': message,
                    'assessment_id': str(assessment.id)
                })
            else:
                return Response(
                    {'error': message},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error submitting assessment {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def review(self, request, pk=None):
        """
        Review submitted assessment.
        
        POST /api/investment/assessments/{id}/review/
        """
        assessment = self.get_object()
        
        # Check review permission
        if not request.user.has_perm('investment.review_assessment'):
            return Response(
                {'error': 'You do not have permission to review assessments'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = AssessmentReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            result = self.service.review_assessment(
                str(assessment.id),
                str(request.user.id),
                serializer.validated_data['decision'],
                serializer.validated_data['comments']
            )
            
            return Response(result)
            
        except Exception as e:
            logger.error(f"Error reviewing assessment {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def scores(self, request, pk=None):
        """
        Get assessment scores.
        
        GET /api/investment/assessments/{id}/scores/
        """
        assessment = self.get_object()
        
        try:
            scores = self.service.calculate_scores(str(assessment.id))
            
            return Response({
                'assessment_id': str(assessment.id),
                'scores': scores,
                'calculated_at': timezone.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error calculating scores for assessment {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def generate_report(self, request, pk=None):
        """
        Generate assessment report.
        
        POST /api/investment/assessments/{id}/generate_report/
        """
        assessment = self.get_object()
        serializer = ReportGenerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            report_content = self.service.generate_report(
                str(assessment.id),
                format=serializer.validated_data.get('format', 'pdf')
            )
            
            # Return file response
            from django.http import HttpResponse
            
            format_type = serializer.validated_data.get('format', 'pdf')
            content_types = {
                'pdf': 'application/pdf',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'html': 'text/html'
            }
            
            response = HttpResponse(
                report_content,
                content_type=content_types.get(format_type, 'application/octet-stream')
            )
            
            filename = f"assessment_report_{assessment.id}.{format_type}"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response
            
        except Exception as e:
            logger.error(f"Error generating report for assessment {pk}: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def benchmarks(self, request):
        """
        Get sector benchmarks.
        
        GET /api/investment/assessments/benchmarks/
        """
        serializer = BenchmarkSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        
        try:
            benchmarks = self.service.get_benchmarks(
                serializer.validated_data['sector'],
                serializer.validated_data['assessment_type']
            )
            
            return Response(benchmarks)
            
        except Exception as e:
            logger.error(f"Error getting benchmarks: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )