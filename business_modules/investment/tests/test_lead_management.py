"""
Lead Management Service Tests

Tests for lead scoring, qualification, and workflow automation.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model

from business_modules.investment.services import LeadManagementServiceImpl
from business_modules.investment.models import (
    Lead, LeadActivity, LeadScoringModel, LeadScoringResult
)

User = get_user_model()


class TestLeadManagementService(TestCase):
    """Test lead management service functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.service = LeadManagementServiceImpl()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test group
        from django.contrib.auth.models import Group
        self.group = Group.objects.create(name='test_group')
        self.user.groups.add(self.group)
        
        # Mock external dependencies
        self.mock_event_publisher = Mock()
        self.mock_cache_manager = Mock()
        self.mock_workflow_engine = Mock()
        self.mock_websocket_manager = Mock()
        
        # Patch dependencies
        self.patches = [
            patch('business_modules.investment.services.lead_management.event_publisher', self.mock_event_publisher),
            patch('business_modules.investment.services.lead_management.cache_manager', self.mock_cache_manager),
            patch('business_modules.investment.services.lead_management.workflow_engine', self.mock_workflow_engine),
            patch('business_modules.investment.services.lead_management.websocket_manager', self.mock_websocket_manager),
        ]
        
        for p in self.patches:
            p.start()
    
    def tearDown(self):
        """Clean up patches."""
        for p in self.patches:
            p.stop()
    
    def test_create_lead_with_auto_scoring(self):
        """Test lead creation with automatic scoring."""
        # Create scoring model
        scoring_model = LeadScoringModel.objects.create(
            name='Default Model',
            model_type='weighted_average',
            is_active=True,
            configuration={
                'weights': {
                    'business_alignment': 0.3,
                    'market_presence': 0.3,
                    'financial_strength': 0.2,
                    'strategic_fit': 0.2
                }
            }
        )
        
        # Prepare lead data
        lead_data = {
            'company_name': 'TechStart Inc',
            'contact_name': 'John Doe',
            'contact_email': 'john@techstart.com',
            'contact_phone': '+1234567890',
            'sector': 'technology',
            'source': 'website',
            'description': 'Innovative AI startup',
            'metadata': {
                'employees': 50,
                'revenue': '5000000',
                'founded_year': 2020
            },
            'group_id': str(self.group.id),
            'created_by_id': str(self.user.id)
        }
        
        # Execute
        result = self.service.create_lead(lead_data)
        
        # Verify
        assert 'id' in result
        assert result['status'] == 'new'
        assert 'score' in result
        assert result['score'] > 0
        
        # Check database
        lead = Lead.objects.get(id=result['id'])
        assert lead.company_name == 'TechStart Inc'
        assert lead.score > 0
        
        # Check activity created
        activity = LeadActivity.objects.filter(lead=lead).first()
        assert activity is not None
        assert activity.activity_type == 'created'
        
        # Check events published
        self.mock_event_publisher.publish.assert_any_call(
            'lead.created',
            {
                'lead_id': result['id'],
                'company_name': 'TechStart Inc',
                'score': result['score']
            }
        )
    
    def test_score_lead_with_ml_model(self):
        """Test lead scoring with ML model."""
        # Create lead
        lead = Lead.objects.create(
            company_name='MLTestCo',
            contact_name='Jane Smith',
            contact_email='jane@mltestco.com',
            sector='fintech',
            metadata={
                'employees': 100,
                'revenue': '10000000',
                'growth_rate': '150%',
                'funding_stage': 'Series A'
            }
        )
        
        # Create ML scoring model
        ml_model = LeadScoringModel.objects.create(
            name='ML Model',
            model_type='ml_classifier',
            is_active=True,
            configuration={
                'model_path': 'models/lead_scorer_v1.pkl',
                'feature_columns': [
                    'employees', 'revenue', 'sector_encoded',
                    'growth_rate', 'funding_stage_encoded'
                ]
            }
        )
        
        # Mock ML prediction
        with patch('business_modules.investment.services.lead_management.joblib') as mock_joblib:
            mock_model = Mock()
            mock_model.predict_proba.return_value = [[0.15, 0.85]]  # 85% probability
            mock_joblib.load.return_value = mock_model
            
            # Execute
            result = self.service.score_lead(str(lead.id), model_id=str(ml_model.id))
        
        # Verify
        assert result['score'] == 85.0
        assert result['model_used'] == 'ML Model'
        assert 'components' in result
        
        # Check scoring result saved
        scoring_result = LeadScoringResult.objects.filter(lead=lead).first()
        assert scoring_result is not None
        assert scoring_result.score == 85.0
        assert scoring_result.model_used == ml_model
    
    def test_qualify_lead_automatic(self):
        """Test automatic lead qualification based on score."""
        # Create high-scoring lead
        lead = Lead.objects.create(
            company_name='QualifiedCo',
            contact_name='Bob Manager',
            contact_email='bob@qualified.com',
            sector='enterprise',
            score=85.0,
            status='new'
        )
        
        # Execute qualification
        qualified, reason = self.service.qualify_lead(str(lead.id))
        
        # Verify
        assert qualified is True
        assert 'Score 85.0 exceeds threshold' in reason
        
        # Check lead status updated
        lead.refresh_from_db()
        assert lead.status == 'qualified'
        assert lead.qualified_date is not None
        
        # Check workflow started
        self.mock_workflow_engine.start_workflow.assert_called_once()
        workflow_call = self.mock_workflow_engine.start_workflow.call_args
        assert workflow_call[0][0] == 'lead_qualification'
        assert workflow_call[0][1]['lead_id'] == str(lead.id)
    
    def test_qualify_lead_manual_override(self):
        """Test manual lead qualification with low score."""
        # Create low-scoring lead
        lead = Lead.objects.create(
            company_name='ManualQualifyCo',
            contact_name='Alice Director',
            contact_email='alice@manual.com',
            sector='startup',
            score=45.0,
            status='new',
            metadata={'manual_review_notes': 'Strategic importance'}
        )
        
        # Force qualification
        qualified, reason = self.service.qualify_lead(
            str(lead.id),
            force=True,
            reason='Strategic partner opportunity'
        )
        
        # Verify
        assert qualified is True
        assert 'Manually qualified' in reason
        
        # Check activity logged
        activity = LeadActivity.objects.filter(
            lead=lead,
            activity_type='qualification'
        ).first()
        assert activity is not None
        assert 'Strategic partner opportunity' in activity.description
    
    def test_assign_lead_auto_distribution(self):
        """Test automatic lead assignment with load balancing."""
        # Create multiple users
        users = []
        for i in range(3):
            user = User.objects.create_user(
                username=f'sales{i}',
                email=f'sales{i}@example.com',
                password='pass123',
                is_active=True
            )
            user.groups.add(self.group)
            users.append(user)
        
        # Create leads with existing assignments
        Lead.objects.create(
            company_name='Existing1',
            contact_email='e1@test.com',
            assigned_to=users[0]
        )
        Lead.objects.create(
            company_name='Existing2',
            contact_email='e2@test.com',
            assigned_to=users[0]
        )
        
        # Create new lead to assign
        lead = Lead.objects.create(
            company_name='NewAssignCo',
            contact_name='New Contact',
            contact_email='new@assign.com',
            sector='technology',
            status='qualified'
        )
        
        # Execute auto-assignment
        result = self.service.assign_lead(str(lead.id))
        
        # Verify
        assert result['assigned'] is True
        assert result['assigned_to'] in [str(u.id) for u in users]
        
        # Should not assign to users[0] due to higher load
        lead.refresh_from_db()
        assert lead.assigned_to != users[0]
        
        # Check notification sent
        self.mock_websocket_manager.send_to_channel.assert_called()
        ws_call = self.mock_websocket_manager.send_to_channel.call_args[0]
        assert ws_call[0] == 'lead-activity'
        assert ws_call[1]['type'] == 'lead.assigned'
    
    def test_assign_lead_with_expertise_matching(self):
        """Test lead assignment based on expertise matching."""
        # Create user with sector expertise
        expert_user = User.objects.create_user(
            username='fintech_expert',
            email='expert@fintech.com',
            password='pass123'
        )
        expert_user.groups.add(self.group)
        
        # Add expertise metadata
        from django.contrib.auth import get_user_model
        User = get_user_model()
        # Simulate user profile with expertise
        expert_user.metadata = {'expertise_sectors': ['fintech', 'blockchain']}
        expert_user.save()
        
        # Create fintech lead
        lead = Lead.objects.create(
            company_name='FintechStartup',
            contact_email='contact@fintech.com',
            sector='fintech',
            status='qualified'
        )
        
        # Execute assignment
        result = self.service.assign_lead(str(lead.id))
        
        # Verify expert was chosen
        assert result['assigned_to'] == str(expert_user.id)
        assert result['assignment_reason'] == 'expertise_match'
    
    def test_get_pipeline_analytics(self):
        """Test pipeline analytics generation."""
        # Create test data
        statuses = ['new', 'qualified', 'contacted', 'negotiating', 'converted', 'lost']
        base_date = timezone.now()
        
        for i in range(30):
            for status in statuses:
                Lead.objects.create(
                    company_name=f'Company_{status}_{i}',
                    contact_email=f'{status}{i}@test.com',
                    status=status,
                    score=50 + (i % 50),
                    created_date=base_date - timedelta(days=i),
                    sector='technology' if i % 2 == 0 else 'healthcare'
                )
        
        # Execute analytics
        analytics = self.service.get_pipeline_analytics()
        
        # Verify structure
        assert 'summary' in analytics
        assert 'funnel' in analytics
        assert 'trends' in analytics
        assert 'performance' in analytics
        
        # Verify summary data
        summary = analytics['summary']
        assert summary['total_leads'] == 180  # 30 * 6 statuses
        assert 'conversion_rate' in summary
        assert 'average_score' in summary
        
        # Verify funnel data
        funnel = analytics['funnel']
        assert len(funnel) == len(statuses)
        assert all('status' in stage for stage in funnel)
        assert all('count' in stage for stage in funnel)
        
        # Check cache was used
        self.mock_cache_manager.get.assert_called()
    
    def test_process_overdue_leads(self):
        """Test overdue lead processing and notifications."""
        # Create overdue leads
        overdue_date = timezone.now() - timedelta(days=10)
        
        overdue_leads = []
        for i in range(3):
            lead = Lead.objects.create(
                company_name=f'OverdueCo{i}',
                contact_email=f'overdue{i}@test.com',
                status='qualified',
                next_action_date=overdue_date,
                assigned_to=self.user
            )
            overdue_leads.append(lead)
        
        # Create non-overdue lead
        Lead.objects.create(
            company_name='CurrentCo',
            contact_email='current@test.com',
            status='qualified',
            next_action_date=timezone.now() + timedelta(days=1),
            assigned_to=self.user
        )
        
        # Mock notification service
        with patch('business_modules.investment.services.lead_management.notification_service') as mock_notif:
            # Execute
            processed = self.service.process_overdue_leads()
        
        # Verify
        assert len(processed) == 3
        
        # Check notifications sent
        assert mock_notif.send_notification.call_count == 3
        
        # Check activities created
        for lead in overdue_leads:
            activity = LeadActivity.objects.filter(
                lead=lead,
                activity_type='overdue_alert'
            ).first()
            assert activity is not None
    
    def test_lead_lifecycle_tracking(self):
        """Test complete lead lifecycle tracking."""
        # Create lead
        lead = Lead.objects.create(
            company_name='LifecycleCo',
            contact_email='lifecycle@test.com',
            status='new'
        )
        
        # Track lifecycle stages
        stages = [
            ('qualification', 'qualified'),
            ('first_contact', 'contacted'),
            ('meeting', 'meeting_scheduled'),
            ('proposal', 'proposal_sent'),
            ('negotiation', 'negotiating'),
            ('close', 'converted')
        ]
        
        for activity_type, new_status in stages:
            # Update status
            lead.status = new_status
            lead.save()
            
            # Create activity
            LeadActivity.objects.create(
                lead=lead,
                activity_type=activity_type,
                description=f'{activity_type} completed',
                user=self.user
            )
            
            # Simulate time passing
            lead.last_activity_date = timezone.now()
            lead.save()
        
        # Get lead history
        activities = LeadActivity.objects.filter(lead=lead).order_by('created_date')
        
        # Verify complete history
        assert activities.count() == len(stages)
        
        # Calculate conversion time
        conversion_time = (
            lead.last_activity_date - lead.created_date
        ).total_seconds()
        
        assert conversion_time > 0
    
    def test_real_time_lead_updates(self):
        """Test real-time lead updates via WebSocket."""
        # Create lead
        lead = Lead.objects.create(
            company_name='RealtimeCo',
            contact_email='realtime@test.com',
            status='new'
        )
        
        # Update lead score
        self.service.score_lead(str(lead.id))
        
        # Verify WebSocket notifications
        ws_calls = self.mock_websocket_manager.send_to_channel.call_args_list
        
        # Should have notifications for creation and scoring
        assert len(ws_calls) >= 2
        
        # Check notification format
        scoring_notification = next(
            c for c in ws_calls
            if 'score' in str(c)
        )
        channel, data = scoring_notification[0]
        assert channel == 'lead-activity'
        assert 'lead_id' in data['data']
    
    def test_lead_tagging_and_filtering(self):
        """Test lead tagging and tag-based filtering."""
        # Create leads with tags
        tags_map = {
            'high_value': ['enterprise', 'funded', 'urgent'],
            'technical': ['saas', 'api', 'integration'],
            'strategic': ['partner', 'channel', 'ecosystem']
        }
        
        created_leads = {}
        for tag_group, tags in tags_map.items():
            lead = Lead.objects.create(
                company_name=f'{tag_group.title()}Co',
                contact_email=f'{tag_group}@test.com',
                tags=tags
            )
            created_leads[tag_group] = lead
        
        # Test tag-based filtering
        enterprise_leads = Lead.objects.filter(tags__contains=['enterprise'])
        assert enterprise_leads.count() == 1
        assert enterprise_leads.first() == created_leads['high_value']
        
        # Test multiple tag filtering
        saas_api_leads = Lead.objects.filter(
            tags__contains=['saas']
        ).filter(
            tags__contains=['api']
        )
        assert saas_api_leads.count() == 1
        assert saas_api_leads.first() == created_leads['technical']


class TestLeadManagementIntegration(TransactionTestCase):
    """Integration tests for lead management with platform services."""
    
    def setUp(self):
        """Set up integration test environment."""
        self.service = LeadManagementServiceImpl()
        
        # Create test user
        self.user = User.objects.create_user(
            username='integrationuser',
            email='integration@test.com',
            password='testpass123'
        )
    
    @patch('business_modules.investment.services.lead_management.workflow_engine')
    @patch('business_modules.investment.services.lead_management.event_publisher')
    def test_lead_to_partner_conversion_flow(self, mock_events, mock_workflow):
        """Test complete lead to partner conversion flow."""
        # Create qualified lead
        lead = Lead.objects.create(
            company_name='ConversionTestCo',
            contact_name='Convert Test',
            contact_email='convert@test.com',
            sector='technology',
            score=90.0,
            status='qualified',
            assigned_to=self.user
        )
        
        # Simulate conversion process
        lead.status = 'converted'
        lead.converted_date = timezone.now()
        lead.save()
        
        # Create partner from lead
        from business_modules.investment.models import DevelopmentPartner
        
        partner = DevelopmentPartner.objects.create(
            name=lead.company_name,
            sector=lead.sector,
            lead=lead,
            metadata={'converted_from_lead': str(lead.id)}
        )
        
        lead.converted_to_partner = partner
        lead.save()
        
        # Verify conversion
        assert lead.status == 'converted'
        assert lead.converted_to_partner == partner
        assert partner.lead == lead
        
        # Check events
        mock_events.publish.assert_any_call(
            'lead.converted',
            {
                'lead_id': str(lead.id),
                'partner_id': str(partner.id),
                'conversion_date': lead.converted_date.isoformat()
            }
        )
    
    def test_concurrent_lead_scoring(self):
        """Test thread-safe concurrent lead scoring."""
        from concurrent.futures import ThreadPoolExecutor
        import threading
        
        # Create multiple leads
        leads = []
        for i in range(10):
            lead = Lead.objects.create(
                company_name=f'ConcurrentCo{i}',
                contact_email=f'concurrent{i}@test.com',
                sector='technology'
            )
            leads.append(lead)
        
        # Track scoring results
        results = []
        results_lock = threading.Lock()
        
        def score_lead_thread(lead_id):
            result = self.service.score_lead(lead_id)
            with results_lock:
                results.append(result)
        
        # Execute concurrent scoring
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for lead in leads:
                future = executor.submit(score_lead_thread, str(lead.id))
                futures.append(future)
            
            # Wait for completion
            for future in futures:
                future.result()
        
        # Verify all leads scored
        assert len(results) == 10
        assert all('score' in r for r in results)
        
        # Verify no duplicate scoring results
        scored_lead_ids = [r['lead_id'] for r in results]
        assert len(scored_lead_ids) == len(set(scored_lead_ids))
    
    @patch('business_modules.investment.services.lead_management.rate_limiter')
    def test_rate_limiting_protection(self, mock_limiter):
        """Test rate limiting for lead operations."""
        # Configure rate limiter
        mock_limiter.check_rate_limit.return_value = (True, None)
        
        # Create many leads quickly
        for i in range(100):
            self.service.create_lead({
                'company_name': f'RateLimitCo{i}',
                'contact_email': f'rate{i}@test.com',
                'sector': 'technology'
            })
        
        # Verify rate limiter was checked
        assert mock_limiter.check_rate_limit.call_count >= 100
        
        # Simulate rate limit hit
        mock_limiter.check_rate_limit.return_value = (False, 'Rate limit exceeded')
        
        # Next creation should fail
        with pytest.raises(Exception) as exc_info:
            self.service.create_lead({
                'company_name': 'BlockedCo',
                'contact_email': 'blocked@test.com'
            })
        
        assert 'Rate limit' in str(exc_info.value)