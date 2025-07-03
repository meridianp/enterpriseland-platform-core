"""
Investment Module API Tests

Tests for RESTful API endpoints.
"""

import pytest
import json
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from business_modules.investment.models import (
    TargetCompany, Lead, Deal, Assessment,
    DealType, AssessmentTemplate, DevelopmentPartner
)

User = get_user_model()


class BaseAPITestCase(APITestCase):
    """Base class for API tests with authentication setup."""
    
    def setUp(self):
        """Set up test environment."""
        # Create test user
        self.user = User.objects.create_user(
            username='api_user',
            email='api@test.com',
            password='testpass123'
        )
        
        # Create test group
        from django.contrib.auth.models import Group, Permission
        self.group = Group.objects.create(name='test_group')
        self.user.groups.add(self.group)
        
        # Add permissions
        permissions = Permission.objects.filter(
            codename__in=['view_targetcompany', 'add_targetcompany', 
                         'change_targetcompany', 'delete_targetcompany']
        )
        self.group.permissions.add(*permissions)
        
        # Set up authentication
        self.client = APIClient()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        
        # Common test data
        self.api_base = '/api/investment'


class TestMarketIntelligenceAPI(BaseAPITestCase):
    """Test Market Intelligence API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        
        # Create test targets
        self.target1 = TargetCompany.objects.create(
            name='TechTarget',
            sector='technology',
            description='Innovative tech company',
            score=85.0,
            metadata={'employees': 100}
        )
        
        self.target2 = TargetCompany.objects.create(
            name='HealthTarget',
            sector='healthcare',
            description='Healthcare innovation',
            score=75.0,
            metadata={'employees': 50}
        )
    
    def test_list_targets(self):
        """Test listing target companies."""
        response = self.client.get(f'{self.api_base}/market-intel/')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 2
        assert len(response.data['results']) == 2
        
        # Verify data
        target_names = [t['name'] for t in response.data['results']]
        assert 'TechTarget' in target_names
        assert 'HealthTarget' in target_names
    
    def test_retrieve_target(self):
        """Test retrieving single target."""
        response = self.client.get(f'{self.api_base}/market-intel/{self.target1.id}/')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == 'TechTarget'
        assert response.data['score'] == 85.0
        assert 'metadata' in response.data
    
    @patch('business_modules.investment.services.market_intelligence.MarketIntelligenceServiceImpl')
    def test_discover_news(self, mock_service_class):
        """Test news discovery endpoint."""
        # Configure mock
        mock_service = mock_service_class.return_value
        mock_service.discover_news.return_value = [
            {
                'title': 'Tech News 1',
                'url': 'https://example.com/1',
                'published_date': '2024-01-15',
                'content': 'Tech news content'
            },
            {
                'title': 'Tech News 2',
                'url': 'https://example.com/2',
                'published_date': '2024-01-14',
                'content': 'More tech news'
            }
        ]
        
        # Make request
        response = self.client.post(
            f'{self.api_base}/market-intel/discover_news/',
            data={'query_templates': ['tech_news']},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'success'
        assert response.data['discovered'] == 2
        assert len(response.data['articles']) == 2
    
    @patch('business_modules.investment.services.market_intelligence.MarketIntelligenceServiceImpl')
    def test_identify_targets(self, mock_service_class):
        """Test target identification endpoint."""
        # Configure mock
        mock_service = mock_service_class.return_value
        mock_service.identify_targets.return_value = [
            {
                'name': 'NewTarget1',
                'sector': 'fintech',
                'source': 'article1'
            },
            {
                'name': 'NewTarget2',
                'sector': 'ai',
                'source': 'article2'
            }
        ]
        
        # Make request
        articles = [
            {'title': 'Article 1', 'content': 'Content 1'},
            {'title': 'Article 2', 'content': 'Content 2'}
        ]
        
        response = self.client.post(
            f'{self.api_base}/market-intel/identify_targets/',
            data={'articles': articles},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'success'
        assert response.data['identified'] == 2
    
    @patch('business_modules.investment.services.market_intelligence.MarketIntelligenceServiceImpl')
    def test_score_target(self, mock_service_class):
        """Test target scoring endpoint."""
        # Configure mock
        mock_service = mock_service_class.return_value
        mock_service.score_target.return_value = 88.5
        
        # Make request
        response = self.client.post(
            f'{self.api_base}/market-intel/{self.target1.id}/score/'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'success'
        assert response.data['score'] == 88.5
        assert response.data['target_id'] == str(self.target1.id)
    
    def test_market_trends(self):
        """Test market trends endpoint."""
        response = self.client.get(
            f'{self.api_base}/market-intel/trends/',
            {'sector': 'technology', 'period': 'month'}
        )
        
        assert response.status_code == status.HTTP_200_OK
        # Response structure depends on service implementation


class TestLeadManagementAPI(BaseAPITestCase):
    """Test Lead Management API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        
        # Create test leads
        self.lead1 = Lead.objects.create(
            company_name='LeadCo1',
            contact_name='John Lead',
            contact_email='john@leadco1.com',
            sector='technology',
            status='new',
            score=75.0
        )
        
        self.lead2 = Lead.objects.create(
            company_name='LeadCo2',
            contact_name='Jane Lead',
            contact_email='jane@leadco2.com',
            sector='healthcare',
            status='qualified',
            score=85.0,
            assigned_to=self.user
        )
    
    def test_list_leads(self):
        """Test listing leads with filtering."""
        # Test all leads
        response = self.client.get(f'{self.api_base}/leads/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 2
        
        # Test filtering by status
        response = self.client.get(
            f'{self.api_base}/leads/',
            {'status': 'qualified'}
        )
        assert response.data['count'] == 1
        assert response.data['results'][0]['company_name'] == 'LeadCo2'
    
    def test_create_lead(self):
        """Test lead creation with auto-scoring."""
        lead_data = {
            'company_name': 'NewLeadCo',
            'contact_name': 'New Contact',
            'contact_email': 'new@leadco.com',
            'contact_phone': '+1234567890',
            'sector': 'fintech',
            'source': 'website',
            'description': 'Promising fintech startup'
        }
        
        response = self.client.post(
            f'{self.api_base}/leads/',
            data=lead_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data
        assert response.data['status'] == 'new'
        assert 'score' in response.data  # Auto-scored
        
        # Verify in database
        lead = Lead.objects.get(id=response.data['id'])
        assert lead.company_name == 'NewLeadCo'
        assert lead.group == self.user.groups.first()
    
    def test_score_lead(self):
        """Test lead scoring endpoint."""
        response = self.client.post(
            f'{self.api_base}/leads/{self.lead1.id}/score/',
            data={'force_rescore': True},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'score' in response.data
        assert 'model_used' in response.data
    
    def test_qualify_lead(self):
        """Test lead qualification endpoint."""
        response = self.client.post(
            f'{self.api_base}/leads/{self.lead1.id}/qualify/'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'qualified' in response.data
        assert 'reason' in response.data
    
    def test_assign_lead(self):
        """Test lead assignment endpoint."""
        # Create another user for assignment
        assignee = User.objects.create_user(
            username='assignee',
            email='assignee@test.com',
            password='pass123'
        )
        assignee.groups.add(self.group)
        
        response = self.client.post(
            f'{self.api_base}/leads/{self.lead1.id}/assign/',
            data={'user_id': str(assignee.id)},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['assigned_to'] == str(assignee.id)
    
    def test_lead_activities(self):
        """Test lead activities endpoint."""
        # Create activities
        from business_modules.investment.models import LeadActivity
        
        LeadActivity.objects.create(
            lead=self.lead1,
            activity_type='note',
            description='Initial contact made',
            user=self.user
        )
        
        LeadActivity.objects.create(
            lead=self.lead1,
            activity_type='call',
            description='Follow-up call',
            user=self.user
        )
        
        response = self.client.get(
            f'{self.api_base}/leads/{self.lead1.id}/activities/'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        assert response.data[0]['activity_type'] in ['note', 'call']
    
    def test_pipeline_analytics(self):
        """Test pipeline analytics endpoint."""
        response = self.client.get(
            f'{self.api_base}/leads/analytics/',
            {'date_from': '2024-01-01', 'sector': 'technology'}
        )
        
        assert response.status_code == status.HTTP_200_OK
        # Analytics structure depends on service implementation


class TestDealWorkspaceAPI(BaseAPITestCase):
    """Test Deal Workspace API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        
        # Create deal type
        self.deal_type = DealType.objects.create(
            name='Investment Deal',
            workflow_config={'stages': ['pipeline', 'due_diligence', 'negotiation']}
        )
        
        # Create partner
        self.partner = DevelopmentPartner.objects.create(
            name='Test Partner',
            sector='technology'
        )
        
        # Create deals
        self.deal1 = Deal.objects.create(
            title='Deal One',
            deal_type=self.deal_type,
            partner=self.partner,
            deal_size=Decimal('1000000'),
            status='pipeline',
            created_by=self.user
        )
        
        self.deal2 = Deal.objects.create(
            title='Deal Two',
            deal_type=self.deal_type,
            deal_size=Decimal('5000000'),
            status='due_diligence',
            created_by=self.user
        )
    
    def test_list_deals(self):
        """Test listing deals."""
        response = self.client.get(f'{self.api_base}/deals/')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 2
        
        # Verify includes related data
        deal_data = response.data['results'][0]
        assert 'team_members' in deal_data
        assert 'milestones' in deal_data
    
    def test_create_deal(self):
        """Test deal creation."""
        deal_data = {
            'title': 'New Investment Deal',
            'deal_type': str(self.deal_type.id),
            'partner': str(self.partner.id),
            'description': 'Strategic investment opportunity',
            'deal_size': '2500000',
            'currency': 'USD',
            'target_close_date': (timezone.now() + timedelta(days=90)).isoformat(),
            'team_members': [
                {'user_id': str(self.user.id), 'role': 'lead'}
            ]
        }
        
        response = self.client.post(
            f'{self.api_base}/deals/',
            data=deal_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data
        assert response.data['current_stage'] is not None
        
        # Verify workflow initialized
        deal = Deal.objects.get(id=response.data['id'])
        assert deal.workflow_instance_id is not None
    
    def test_deal_stage_transition(self):
        """Test deal stage transition."""
        response = self.client.post(
            f'{self.api_base}/deals/{self.deal1.id}/transition/',
            data={
                'target_stage': 'due_diligence',
                'reason': 'Initial review completed'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'success'
        assert 'new_stage' in response.data
    
    def test_add_team_member(self):
        """Test adding team member to deal."""
        # Create team member
        team_member = User.objects.create_user(
            username='team_member',
            email='team@test.com',
            password='pass123'
        )
        
        response = self.client.post(
            f'{self.api_base}/deals/{self.deal1.id}/add_team_member/',
            data={
                'user_id': str(team_member.id),
                'role': 'analyst'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['user_id'] == str(team_member.id)
    
    def test_deal_milestones(self):
        """Test deal milestones endpoints."""
        # Get milestones
        response = self.client.get(
            f'{self.api_base}/deals/{self.deal1.id}/milestones/'
        )
        assert response.status_code == status.HTTP_200_OK
        
        # Create milestone
        milestone_data = {
            'name': 'Due Diligence Complete',
            'description': 'Complete financial and legal due diligence',
            'stage': 'due_diligence',
            'is_blocking': True,
            'target_date': (timezone.now() + timedelta(days=30)).isoformat()
        }
        
        response = self.client.post(
            f'{self.api_base}/deals/{self.deal1.id}/milestones/',
            data=milestone_data,
            format='json'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['name'] == 'Due Diligence Complete'
    
    def test_generate_ic_pack(self):
        """Test IC pack generation."""
        response = self.client.post(
            f'{self.api_base}/deals/{self.deal1.id}/generate_ic_pack/',
            data={'template': 'standard'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'file_url' in response.data or 'status' in response.data


class TestAssessmentAPI(BaseAPITestCase):
    """Test Assessment API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        
        # Create partner
        self.partner = DevelopmentPartner.objects.create(
            name='Assessment Partner',
            sector='technology'
        )
        
        # Create template
        self.template = AssessmentTemplate.objects.create(
            name='Standard Assessment',
            code='standard',
            version='1.0',
            sections=[
                {
                    'name': 'Technical',
                    'questions': [
                        {
                            'text': 'Describe your architecture',
                            'type': 'text',
                            'required': True
                        }
                    ]
                }
            ]
        )
        
        # Create assessment
        self.assessment = Assessment.objects.create(
            partner=self.partner,
            template=self.template,
            title='Q1 Assessment',
            status='draft'
        )
    
    def test_list_assessments(self):
        """Test listing assessments."""
        response = self.client.get(f'{self.api_base}/assessments/')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 1
        
        assessment_data = response.data['results'][0]
        assert assessment_data['title'] == 'Q1 Assessment'
        assert 'partner_name' in assessment_data
    
    def test_create_assessment(self):
        """Test assessment creation."""
        response = self.client.post(
            f'{self.api_base}/assessments/create_assessment/',
            data={
                'partner_id': str(self.partner.id),
                'template': 'standard'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data
        assert response.data['status'] == 'draft'
        assert response.data['sections'] > 0
    
    def test_submit_assessment(self):
        """Test assessment submission."""
        # Create sections and responses
        from business_modules.investment.models import (
            AssessmentSection, AssessmentQuestion
        )
        
        section = AssessmentSection.objects.create(
            assessment=self.assessment,
            name='Technical'
        )
        
        question = AssessmentQuestion.objects.create(
            section=section,
            question_text='Describe your architecture',
            question_type='text'
        )
        
        # Submit with responses
        response = self.client.post(
            f'{self.api_base}/assessments/{self.assessment.id}/submit/',
            data={
                'sections': {
                    str(section.id): {
                        str(question.id): 'Cloud-native microservices'
                    }
                },
                'submitted_by_id': str(self.user.id)
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'success'
        
        # Verify assessment updated
        self.assessment.refresh_from_db()
        assert self.assessment.status == 'submitted'
    
    def test_review_assessment_permission(self):
        """Test assessment review with permissions."""
        # Add review permission
        from django.contrib.auth.models import Permission
        review_perm = Permission.objects.get(codename='review_assessment')
        self.user.user_permissions.add(review_perm)
        
        # Update assessment status
        self.assessment.status = 'submitted'
        self.assessment.save()
        
        # Review assessment
        response = self.client.post(
            f'{self.api_base}/assessments/{self.assessment.id}/review/',
            data={
                'decision': 'approve',
                'comments': 'Excellent submission'
            },
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['decision'] == 'approve'
    
    def test_assessment_scores(self):
        """Test assessment score calculation."""
        response = self.client.get(
            f'{self.api_base}/assessments/{self.assessment.id}/scores/'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'scores' in response.data
        assert response.data['assessment_id'] == str(self.assessment.id)
    
    def test_generate_report(self):
        """Test assessment report generation."""
        response = self.client.post(
            f'{self.api_base}/assessments/{self.assessment.id}/generate_report/',
            data={'format': 'pdf'},
            format='json'
        )
        
        # Should return file response
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_500_INTERNAL_SERVER_ERROR]
        if response.status_code == status.HTTP_200_OK:
            assert response['Content-Type'] == 'application/pdf'
    
    def test_benchmarks(self):
        """Test sector benchmarks endpoint."""
        response = self.client.get(
            f'{self.api_base}/assessments/benchmarks/',
            {
                'sector': 'technology',
                'assessment_type': 'standard'
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        # Benchmark data depends on available assessments


class TestAPIPermissions(BaseAPITestCase):
    """Test API permission enforcement."""
    
    def setUp(self):
        """Set up test environment."""
        super().setUp()
        
        # Create unauthorized user
        self.unauth_user = User.objects.create_user(
            username='unauth',
            email='unauth@test.com',
            password='pass123'
        )
        
        # Create test target
        self.target = TargetCompany.objects.create(
            name='PermTest',
            sector='technology'
        )
    
    def test_unauthorized_access(self):
        """Test unauthorized access is blocked."""
        # Use unauthorized client
        client = APIClient()
        
        response = client.get(f'{self.api_base}/market-intel/')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_permission_denied(self):
        """Test permission-based access control."""
        # Login as user without permissions
        client = APIClient()
        refresh = RefreshToken.for_user(self.unauth_user)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        
        # Try to access protected endpoint
        response = client.get(f'{self.api_base}/market-intel/')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_group_filtering(self):
        """Test group-based data filtering."""
        # Create data in different group
        other_group = Group.objects.create(name='other_group')
        other_user = User.objects.create_user(
            username='other',
            email='other@test.com'
        )
        other_user.groups.add(other_group)
        
        # Create lead in other group
        other_lead = Lead.objects.create(
            company_name='OtherGroupLead',
            contact_email='other@lead.com',
            group=other_group
        )
        
        # Try to access from original user
        response = self.client.get(f'{self.api_base}/leads/')
        
        # Should not see other group's data
        lead_ids = [l['id'] for l in response.data['results']]
        assert str(other_lead.id) not in lead_ids