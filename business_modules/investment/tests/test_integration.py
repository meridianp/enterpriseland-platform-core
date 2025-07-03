"""
Investment Module Integration Tests

End-to-end tests for complete business flows.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from business_modules.investment.models import (
    Lead, TargetCompany, Deal, Assessment,
    DevelopmentPartner, DealType, AssessmentTemplate
)
from business_modules.investment.services import (
    MarketIntelligenceServiceImpl,
    LeadManagementServiceImpl,
    DealWorkspaceServiceImpl,
    AssessmentServiceImpl
)

User = get_user_model()


class TestCompleteInvestmentFlow(TransactionTestCase):
    """Test complete investment flow from discovery to partnership."""
    
    def setUp(self):
        """Set up test environment."""
        # Create users
        self.analyst = User.objects.create_user(
            username='analyst',
            email='analyst@test.com',
            password='pass123'
        )
        
        self.manager = User.objects.create_user(
            username='manager',
            email='manager@test.com',
            password='pass123'
        )
        
        # Set up groups and permissions
        from django.contrib.auth.models import Group, Permission
        
        analyst_group = Group.objects.create(name='analysts')
        manager_group = Group.objects.create(name='managers')
        
        self.analyst.groups.add(analyst_group)
        self.manager.groups.add(manager_group)
        
        # Initialize services
        self.market_intel = MarketIntelligenceServiceImpl()
        self.lead_mgmt = LeadManagementServiceImpl()
        self.deal_workspace = DealWorkspaceServiceImpl()
        self.assessment_svc = AssessmentServiceImpl()
        
        # Set up API client
        self.client = APIClient()
        refresh = RefreshToken.for_user(self.analyst)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    
    @patch('business_modules.investment.services.market_intelligence.ServiceRegistry')
    @patch('business_modules.investment.services.market_intelligence.event_publisher')
    def test_discovery_to_lead_conversion(self, mock_events, mock_registry):
        """Test flow from news discovery to lead creation."""
        # Step 1: Discover news
        mock_news_service = Mock()
        mock_news_service.search_news.return_value = [
            {
                'title': 'TechCo Raises $50M Series B',
                'url': 'https://news.example.com/techco',
                'content': 'TechCo, a leading AI startup, announced $50M funding...',
                'published_date': '2024-01-15'
            }
        ]
        
        mock_ai_service = Mock()
        mock_ai_service.extract_companies.return_value = {
            'TechCo': {
                'sector': 'ai',
                'description': 'AI-powered analytics platform',
                'funding_info': '$50M Series B'
            }
        }
        
        mock_registry.return_value.get_service.side_effect = lambda name: {
            'news_aggregator': mock_news_service,
            'ai_analyzer': mock_ai_service
        }.get(name)
        
        # Discover news
        articles = self.market_intel.discover_news()
        assert len(articles) > 0
        
        # Step 2: Identify targets
        targets = self.market_intel.identify_targets(articles)
        assert len(targets) > 0
        
        # Verify target created
        target = TargetCompany.objects.get(name='TechCo')
        assert target.sector == 'ai'
        
        # Step 3: Score target
        score = self.market_intel.score_target({'id': str(target.id)})
        assert score > 0
        
        # Step 4: Convert to lead
        lead_data = {
            'company_name': target.name,
            'contact_email': 'contact@techco.com',
            'sector': target.sector,
            'source': 'market_intelligence',
            'metadata': {
                'target_id': str(target.id),
                'discovery_score': score
            },
            'group_id': str(self.analyst.groups.first().id),
            'created_by_id': str(self.analyst.id)
        }
        
        lead_result = self.lead_mgmt.create_lead(lead_data)
        
        # Verify lead created and scored
        lead = Lead.objects.get(id=lead_result['id'])
        assert lead.company_name == 'TechCo'
        assert lead.score > 0
        
        # Step 5: Qualify lead
        qualified, reason = self.lead_mgmt.qualify_lead(str(lead.id))
        
        if lead.score >= 70:
            assert qualified is True
            assert lead.status == 'qualified'
    
    @patch('business_modules.investment.workflows.lead_qualification.workflow_engine')
    @patch('business_modules.investment.services.lead_management.notification_service')
    def test_lead_to_deal_progression(self, mock_notif, mock_workflow):
        """Test progression from qualified lead to active deal."""
        # Create qualified lead
        lead = Lead.objects.create(
            company_name='QualifiedTechCo',
            contact_name='John Tech',
            contact_email='john@qualifiedtech.com',
            sector='technology',
            score=85.0,
            status='qualified',
            assigned_to=self.analyst
        )
        
        # Progress lead through stages
        stages = [
            ('contacted', 'Initial contact made'),
            ('meeting_scheduled', 'Discovery call scheduled'),
            ('proposal_sent', 'Investment proposal sent'),
            ('negotiating', 'Terms under negotiation')
        ]
        
        for status, description in stages:
            lead.status = status
            lead.save()
            
            # Log activity
            from business_modules.investment.models import LeadActivity
            LeadActivity.objects.create(
                lead=lead,
                activity_type='progress',
                description=description,
                user=self.analyst
            )
        
        # Convert to partner
        partner = DevelopmentPartner.objects.create(
            name=lead.company_name,
            sector=lead.sector,
            lead=lead
        )
        
        lead.status = 'converted'
        lead.converted_to_partner = partner
        lead.save()
        
        # Create deal
        deal_type = DealType.objects.create(
            name='Investment',
            workflow_config={}
        )
        
        deal_data = {
            'title': f'{partner.name} - Series A Investment',
            'deal_type': deal_type,
            'partner': partner,
            'lead': lead,
            'deal_size': Decimal('5000000'),
            'target_close_date': timezone.now() + timedelta(days=90),
            'created_by_id': str(self.analyst.id),
            'group_id': str(self.analyst.groups.first().id)
        }
        
        deal_result = self.deal_workspace.create_deal(deal_data)
        
        # Verify deal created
        deal = Deal.objects.get(id=deal_result['id'])
        assert deal.partner == partner
        assert deal.lead == lead
        assert deal.status == 'pipeline'
    
    def test_deal_approval_and_closing(self):
        """Test deal approval workflow and closing."""
        # Create deal ready for approval
        deal_type = DealType.objects.create(
            name='Investment',
            workflow_config={}
        )
        
        partner = DevelopmentPartner.objects.create(
            name='ApprovalTestCo',
            sector='technology'
        )
        
        deal = Deal.objects.create(
            title='ApprovalTestCo Investment',
            deal_type=deal_type,
            partner=partner,
            deal_size=Decimal('3000000'),
            irr=Decimal('25.5'),
            target_close_date=timezone.now() + timedelta(days=60),
            status='due_diligence',
            created_by=self.analyst
        )
        
        # Add team members
        from business_modules.investment.models import DealTeamMember
        
        DealTeamMember.objects.create(
            deal=deal,
            user=self.analyst,
            role='analyst',
            can_edit=True
        )
        
        DealTeamMember.objects.create(
            deal=deal,
            user=self.manager,
            role='lead',
            can_edit=True,
            can_approve=True
        )
        
        # Complete milestones
        from business_modules.investment.models import DealMilestone
        
        milestones = [
            'Due diligence complete',
            'Legal review complete',
            'Financial model approved',
            'Term sheet finalized'
        ]
        
        for idx, milestone_name in enumerate(milestones):
            DealMilestone.objects.create(
                deal=deal,
                name=milestone_name,
                stage='due_diligence',
                is_blocking=True,
                completed_date=timezone.now(),
                order=idx
            )
        
        # Move to approval stage
        success, message = self.deal_workspace.transition_stage(
            str(deal.id),
            'approval',
            str(self.manager.id)
        )
        
        assert success is True
        deal.refresh_from_db()
        assert deal.current_stage == 'approval'
        
        # Simulate approval process
        from business_modules.investment.models import DealApproval
        
        approval = DealApproval.objects.create(
            deal=deal,
            approver=self.manager,
            approval_type='manager',
            status='approved',
            decision_date=timezone.now(),
            comments='Strong investment opportunity'
        )
        
        # Close deal
        deal.status = 'closed'
        deal.actual_close_date = timezone.now()
        deal.save()
        
        assert deal.status == 'closed'
    
    def test_partner_assessment_flow(self):
        """Test partner assessment and review process."""
        # Create partner
        partner = DevelopmentPartner.objects.create(
            name='AssessmentTestCo',
            sector='technology',
            is_active=True
        )
        
        # Create assessment template
        template = AssessmentTemplate.objects.create(
            name='Annual Review',
            code='annual_review',
            version='1.0',
            sections=[
                {
                    'name': 'Financial Performance',
                    'weight': 0.4,
                    'questions': [
                        {
                            'text': 'Revenue growth rate',
                            'type': 'number',
                            'required': True
                        },
                        {
                            'text': 'Profitability status',
                            'type': 'select',
                            'options': ['profitable', 'break-even', 'loss'],
                            'required': True
                        }
                    ]
                },
                {
                    'name': 'Operational Excellence',
                    'weight': 0.3,
                    'questions': [
                        {
                            'text': 'Team size',
                            'type': 'number',
                            'required': True
                        },
                        {
                            'text': 'Key achievements',
                            'type': 'text',
                            'required': True
                        }
                    ]
                }
            ]
        )
        
        # Create assessment
        assessment_result = self.assessment_svc.create_assessment(
            str(partner.id),
            'annual_review'
        )
        
        assessment = Assessment.objects.get(id=assessment_result['id'])
        assert assessment.status == 'draft'
        
        # Prepare responses
        from business_modules.investment.models import (
            AssessmentSection, AssessmentQuestion
        )
        
        sections = AssessmentSection.objects.filter(assessment=assessment)
        
        submission_data = {
            'sections': {},
            'submitted_by_id': str(self.analyst.id)
        }
        
        for section in sections:
            section_responses = {}
            for question in section.questions.all():
                if question.question_type == 'number':
                    section_responses[str(question.id)] = '25'  # 25% growth
                elif question.question_type == 'select':
                    section_responses[str(question.id)] = 'profitable'
                else:
                    section_responses[str(question.id)] = 'Expanded team, launched new products'
            
            submission_data['sections'][str(section.id)] = section_responses
        
        # Submit assessment
        success, message = self.assessment_svc.submit_assessment(
            str(assessment.id),
            submission_data
        )
        
        assert success is True
        assessment.refresh_from_db()
        assert assessment.status == 'submitted'
        assert assessment.overall_score > 0
        
        # Review assessment
        review_result = self.assessment_svc.review_assessment(
            str(assessment.id),
            str(self.manager.id),
            'approve',
            'Excellent performance across all metrics'
        )
        
        assessment.refresh_from_db()
        assert assessment.status == 'approved'
        assert assessment.approved_by == self.manager


class TestPlatformIntegration(TestCase):
    """Test investment module integration with platform services."""
    
    def setUp(self):
        """Set up test environment."""
        self.user = User.objects.create_user(
            username='platform_user',
            email='platform@test.com',
            password='pass123'
        )
    
    @patch('business_modules.investment.services.market_intelligence.cache_manager')
    @patch('business_modules.investment.services.market_intelligence.event_publisher')
    def test_caching_integration(self, mock_events, mock_cache):
        """Test caching integration across services."""
        # Configure cache mock
        mock_cache.get.return_value = None  # Cache miss
        mock_cache.set.return_value = True
        
        service = MarketIntelligenceServiceImpl()
        
        # Create test data
        target = TargetCompany.objects.create(
            name='CacheTestCo',
            sector='technology'
        )
        
        # First call - cache miss
        trends1 = service.get_market_trends(period='month')
        
        # Verify cache checked and set
        mock_cache.get.assert_called()
        mock_cache.set.assert_called()
        
        # Configure cache hit
        mock_cache.get.return_value = {'cached': True, 'data': 'cached_trends'}
        
        # Second call - cache hit
        trends2 = service.get_market_trends(period='month')
        
        # Verify cache used
        assert trends2['cached'] is True
    
    @patch('business_modules.investment.services.lead_management.websocket_manager')
    @patch('business_modules.investment.services.lead_management.event_publisher')
    def test_realtime_updates(self, mock_events, mock_ws):
        """Test real-time update integration."""
        service = LeadManagementServiceImpl()
        
        # Create lead
        lead_data = {
            'company_name': 'RealtimeTestCo',
            'contact_email': 'realtime@test.com',
            'sector': 'technology',
            'group_id': '123',
            'created_by_id': str(self.user.id)
        }
        
        result = service.create_lead(lead_data)
        
        # Verify WebSocket notification sent
        mock_ws.send_to_channel.assert_called()
        ws_call = mock_ws.send_to_channel.call_args[0]
        assert ws_call[0] == 'lead-activity'
        assert ws_call[1]['type'] == 'lead.created'
        
        # Verify event published
        mock_events.publish.assert_called()
        event_call = mock_events.publish.call_args[0]
        assert event_call[0] == 'lead.created'
    
    @patch('business_modules.investment.workflows.lead_qualification.workflow_engine')
    def test_workflow_integration(self, mock_workflow):
        """Test workflow engine integration."""
        # Configure workflow mock
        mock_instance = Mock()
        mock_instance.id = 'workflow123'
        mock_workflow.start_workflow.return_value = mock_instance
        
        service = LeadManagementServiceImpl()
        
        # Create and qualify lead
        lead = Lead.objects.create(
            company_name='WorkflowTestCo',
            contact_email='workflow@test.com',
            score=85.0,
            status='new'
        )
        
        qualified, reason = service.qualify_lead(str(lead.id))
        
        # Verify workflow started
        assert qualified is True
        mock_workflow.start_workflow.assert_called_once()
        
        workflow_call = mock_workflow.start_workflow.call_args[0]
        assert workflow_call[0] == 'lead_qualification'
        assert workflow_call[1]['lead_id'] == str(lead.id)
    
    @patch('business_modules.investment.services.deal_workspace.saga_orchestrator')
    def test_saga_integration(self, mock_saga):
        """Test saga pattern integration for complex transactions."""
        # Configure saga mock
        mock_saga_instance = Mock()
        mock_saga_instance.id = 'saga123'
        mock_saga.start_saga.return_value = mock_saga_instance
        
        service = DealWorkspaceServiceImpl()
        
        # Create large deal requiring saga
        partner = DevelopmentPartner.objects.create(
            name='SagaTestCo',
            sector='technology'
        )
        
        deal_type = DealType.objects.create(
            name='Large Investment',
            workflow_config={}
        )
        
        deal_data = {
            'title': 'Mega Deal',
            'deal_type': deal_type,
            'partner': partner,
            'deal_size': Decimal('100000000'),  # $100M
            'created_by_id': str(self.user.id),
            'group_id': '123'
        }
        
        # Large deals trigger saga
        result = service.create_deal(deal_data)
        
        # Verify saga started for large deal
        if deal_data['deal_size'] > 50000000:
            mock_saga.start_saga.assert_called()


class TestErrorHandlingAndRecovery(TestCase):
    """Test error handling and recovery scenarios."""
    
    def setUp(self):
        """Set up test environment."""
        self.service = LeadManagementServiceImpl()
    
    def test_transaction_rollback(self):
        """Test transaction rollback on errors."""
        # Create lead that will fail validation
        lead_data = {
            'company_name': 'FailTestCo',
            'contact_email': 'invalid-email',  # Invalid email
            'sector': 'technology'
        }
        
        # Attempt to create lead
        with pytest.raises(Exception):
            self.service.create_lead(lead_data)
        
        # Verify no partial data saved
        assert Lead.objects.filter(company_name='FailTestCo').count() == 0
    
    @patch('business_modules.investment.services.market_intelligence.ServiceRegistry')
    def test_external_service_failure_handling(self, mock_registry):
        """Test graceful handling of external service failures."""
        # Configure service to fail
        mock_registry.return_value.get_service.side_effect = Exception('Service down')
        
        service = MarketIntelligenceServiceImpl()
        
        # Should handle gracefully
        articles = service.discover_news()
        assert articles == []  # Empty result on failure
    
    def test_concurrent_update_handling(self):
        """Test handling of concurrent updates."""
        from django.db import transaction
        import threading
        
        # Create lead
        lead = Lead.objects.create(
            company_name='ConcurrentCo',
            contact_email='concurrent@test.com',
            score=50.0
        )
        
        results = []
        
        def update_lead_score(new_score):
            try:
                with transaction.atomic():
                    lead_copy = Lead.objects.select_for_update().get(id=lead.id)
                    lead_copy.score = new_score
                    lead_copy.save()
                    results.append(new_score)
            except Exception as e:
                results.append(f"Error: {e}")
        
        # Simulate concurrent updates
        threads = []
        for score in [60.0, 70.0, 80.0]:
            thread = threading.Thread(target=update_lead_score, args=(score,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify one of the updates succeeded
        lead.refresh_from_db()
        assert lead.score in [60.0, 70.0, 80.0]