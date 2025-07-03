"""
Investment Module Workflow Tests

Tests for lead qualification, deal approval, and assessment workflows.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
from decimal import Decimal
import asyncio
from django.utils import timezone
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model

from platform_core.workflows import WorkflowContext, WorkflowInstance
from business_modules.investment.workflows import (
    LeadQualificationWorkflow,
    DealApprovalWorkflow,
    AssessmentReviewWorkflow,
    PartnerOnboardingWorkflow
)
from business_modules.investment.models import (
    Lead, Deal, Assessment, DevelopmentPartner
)

User = get_user_model()


class TestLeadQualificationWorkflow(TestCase):
    """Test lead qualification workflow."""
    
    def setUp(self):
        """Set up test environment."""
        self.workflow = LeadQualificationWorkflow()
        
        # Create test user
        self.user = User.objects.create_user(
            username='workflow_user',
            email='workflow@test.com',
            password='testpass123'
        )
        
        # Create test lead
        self.lead = Lead.objects.create(
            company_name='WorkflowTestCo',
            contact_name='Test Contact',
            contact_email='test@workflow.com',
            sector='technology',
            status='new'
        )
        
        # Mock context
        self.mock_context = Mock(spec=WorkflowContext)
        self.mock_context.get.side_effect = self._context_get
        self.mock_context.update.return_value = None
        self.mock_context.set_status.return_value = None
        self.mock_context.started_at = timezone.now()
        
        # Context data
        self.context_data = {
            'lead_id': str(self.lead.id),
            'initiated_by': str(self.user.id)
        }
    
    def _context_get(self, key, default=None):
        """Mock context.get() method."""
        return self.context_data.get(key, default)
    
    @patch('business_modules.investment.workflows.lead_qualification.LeadManagementServiceImpl')
    async def test_score_lead_activity(self, mock_service_class):
        """Test lead scoring activity."""
        # Configure mock
        mock_service = mock_service_class.return_value
        mock_service.score_lead.return_value = {
            'score': 85.0,
            'components': {
                'business_alignment': 90,
                'market_presence': 85,
                'financial_strength': 80,
                'strategic_fit': 85
            },
            'model_id': 'model123'
        }
        
        # Execute activity
        result = await self.workflow.score_lead(self.mock_context)
        
        # Verify
        assert result['score'] == 85.0
        assert 'score_components' in result
        mock_service.score_lead.assert_called_once_with(str(self.lead.id))
        
        # Check activity logged
        from business_modules.investment.models import LeadActivity
        activity = LeadActivity.objects.filter(
            lead=self.lead,
            activity_type='scoring'
        ).first()
        assert activity is not None
    
    @patch('business_modules.investment.workflows.lead_qualification.cache_manager')
    async def test_check_qualification_activity(self, mock_cache):
        """Test qualification checking activity."""
        # Set threshold
        mock_cache.get.return_value = 70.0  # Qualification threshold
        
        # Add score to context
        self.context_data['score'] = 85.0
        
        # Execute activity
        result = await self.workflow.check_qualification(self.mock_context)
        
        # Verify qualified
        assert result['is_qualified'] is True
        assert result['status'] == 'qualified'
        
        # Check lead updated
        self.lead.refresh_from_db()
        assert self.lead.status == 'qualified'
        assert self.lead.qualified_date is not None
    
    @patch('business_modules.investment.workflows.lead_qualification.LeadManagementServiceImpl')
    @patch('business_modules.investment.workflows.lead_qualification.notification_service')
    async def test_assign_lead_activity(self, mock_notif, mock_service_class):
        """Test lead assignment activity."""
        # Configure mocks
        mock_service = mock_service_class.return_value
        mock_service.assign_lead.return_value = {
            'assigned': True,
            'assigned_to': str(self.user.id),
            'assigned_to_name': self.user.get_full_name(),
            'lead_name': self.lead.company_name
        }
        
        # Set qualification status
        self.context_data['is_qualified'] = True
        
        # Execute activity
        result = await self.workflow.assign_lead(self.mock_context)
        
        # Verify
        assert result['assigned'] is True
        assert result['assigned_to'] == str(self.user.id)
        
        # Check notification sent
        mock_notif.send_notification.assert_called_once()
        notif_call = mock_notif.send_notification.call_args
        assert notif_call[1]['user_id'] == str(self.user.id)
        assert notif_call[1]['type'] == 'lead_assignment'
    
    @patch('business_modules.investment.workflows.lead_qualification.notification_service')
    async def test_schedule_followup_activity(self, mock_notif):
        """Test follow-up scheduling activity."""
        # Set context
        self.context_data['assigned_to'] = str(self.user.id)
        
        # Execute activity
        result = await self.workflow.schedule_followup(self.mock_context)
        
        # Verify
        assert result['scheduled'] is True
        assert 'followup_date' in result
        assert 'activity_id' in result
        
        # Check follow-up activity created
        from business_modules.investment.models import LeadActivity
        followup = LeadActivity.objects.filter(
            lead=self.lead,
            activity_type='task'
        ).first()
        assert followup is not None
        assert followup.user_id == self.user.id
        
        # Check reminder scheduled
        mock_notif.schedule_notification.assert_called_once()
    
    async def test_setup_monitoring_activity(self):
        """Test monitoring setup activity."""
        # Mock child workflow creation
        mock_child_workflow = Mock()
        mock_child_workflow.id = 'child123'
        self.mock_context.create_child_workflow.return_value = mock_child_workflow
        
        # Set context
        self.context_data['lead_id'] = str(self.lead.id)
        self.context_data['assigned_to'] = str(self.user.id)
        
        # Execute activity
        result = await self.workflow.setup_monitoring(self.mock_context)
        
        # Verify
        assert result['monitoring_setup'] is True
        assert result['child_workflow_id'] == 'child123'
        
        # Check child workflow created
        self.mock_context.create_child_workflow.assert_called_once_with(
            'lead_progress_monitor',
            {
                'lead_id': str(self.lead.id),
                'assigned_to': str(self.user.id),
                'check_interval_days': 3,
                'escalation_days': 7
            }
        )
    
    @patch('business_modules.investment.workflows.lead_qualification.LeadManagementServiceImpl')
    async def test_complete_workflow_execution(self, mock_service_class):
        """Test complete workflow execution."""
        # Configure mocks
        mock_service = mock_service_class.return_value
        mock_service.score_lead.return_value = {
            'score': 85.0,
            'components': {},
            'model_id': 'model123'
        }
        mock_service.assign_lead.return_value = {
            'assigned': True,
            'assigned_to': str(self.user.id),
            'assigned_to_name': 'Test User',
            'lead_name': self.lead.company_name
        }
        
        # Mock activities as coroutines
        self.workflow.score_lead = AsyncMock(return_value={'score': 85.0})
        self.workflow.check_qualification = AsyncMock(return_value={
            'is_qualified': True,
            'reasons': [],
            'status': 'qualified'
        })
        self.workflow.assign_lead = AsyncMock(return_value={
            'assigned': True,
            'assigned_to': str(self.user.id)
        })
        self.workflow.schedule_followup = AsyncMock(return_value={
            'scheduled': True,
            'followup_date': timezone.now().isoformat()
        })
        self.workflow.setup_monitoring = AsyncMock(return_value={
            'monitoring_setup': True,
            'child_workflow_id': 'child123'
        })
        
        # Execute workflow
        result = await self.workflow.execute(self.mock_context)
        
        # Verify execution flow
        assert result['lead_id'] == str(self.lead.id)
        assert result['qualified'] is True
        assert result['score'] == 85.0
        assert result['assigned_to'] == str(self.user.id)
        assert 'workflow_duration' in result
        
        # Verify all activities called
        self.workflow.score_lead.assert_called_once()
        self.workflow.check_qualification.assert_called_once()
        self.workflow.assign_lead.assert_called_once()
        self.workflow.schedule_followup.assert_called_once()
        self.workflow.setup_monitoring.assert_called_once()


class TestDealApprovalWorkflow(TestCase):
    """Test deal approval workflow."""
    
    def setUp(self):
        """Set up test environment."""
        self.workflow = DealApprovalWorkflow()
        
        # Create test users
        self.users = {}
        roles = ['manager', 'director', 'vp', 'ceo']
        for role in roles:
            user = User.objects.create_user(
                username=f'{role}_user',
                email=f'{role}@test.com',
                password='testpass123'
            )
            # Create approval group
            from django.contrib.auth.models import Group
            group = Group.objects.create(name=f'deal_approver_{role}')
            user.groups.add(group)
            self.users[role] = user
        
        # Create test deal
        from business_modules.investment.models import DealType
        self.deal_type = DealType.objects.create(
            name='Standard Deal',
            workflow_config={}
        )
        
        self.deal = Deal.objects.create(
            title='Test Deal',
            deal_type=self.deal_type,
            deal_size=Decimal('5000000'),  # $5M
            status='pipeline',
            created_by=self.users['manager']
        )
        
        # Mock context
        self.mock_context = Mock(spec=WorkflowContext)
        self.mock_context.get.side_effect = self._context_get
        self.mock_context.update.return_value = None
        self.mock_context.set.return_value = None
        self.mock_context.set_status.return_value = None
        self.mock_context.started_at = timezone.now()
        self.mock_context.workflow_id = 'workflow123'
        
        # Context data
        self.context_data = {
            'deal_id': str(self.deal.id),
            'initiated_by': str(self.users['manager'].id)
        }
    
    def _context_get(self, key, default=None):
        """Mock context.get() method."""
        return self.context_data.get(key, default)
    
    async def test_validate_deal_activity(self):
        """Test deal validation activity."""
        # Add required data to deal
        self.deal.irr = Decimal('15.5')
        self.deal.target_close_date = timezone.now() + timedelta(days=90)
        self.deal.save()
        
        # Execute activity
        result = await self.workflow.validate_deal(self.mock_context)
        
        # Verify
        assert result['is_valid'] is True
        assert result['deal_size'] == 5000000.0
        assert result['deal_category'] == 'medium'  # $5M falls in medium
        assert len(result['errors']) == 0
        
        # Test with missing data
        self.deal.deal_size = None
        self.deal.save()
        
        result = await self.workflow.validate_deal(self.mock_context)
        assert result['is_valid'] is False
        assert 'Deal size not specified' in result['errors']
    
    async def test_identify_approvers_activity(self):
        """Test approver identification activity."""
        # Set deal category
        self.context_data['deal_category'] = 'medium'
        
        # Execute activity
        result = await self.workflow.identify_approvers(self.mock_context)
        
        # Verify
        assert result['approvers_identified'] == 2  # Manager and director for medium deals
        assert len(result['approvers']) == 2
        
        approver_roles = [a['role'] for a in result['approvers']]
        assert 'manager' in approver_roles
        assert 'director' in approver_roles
        assert 'vp' not in approver_roles  # Not required for medium deals
    
    @patch('business_modules.investment.workflows.deal_approval.notification_service')
    async def test_request_approvals_activity(self, mock_notif):
        """Test approval request activity."""
        # Set approvers
        self.context_data['approvers'] = [
            {
                'user_id': str(self.users['manager'].id),
                'name': 'Manager User',
                'role': 'manager',
                'email': 'manager@test.com'
            },
            {
                'user_id': str(self.users['director'].id),
                'name': 'Director User',
                'role': 'director',
                'email': 'director@test.com'
            }
        ]
        self.context_data['deal_category'] = 'medium'
        self.context_data['approval_requirements'] = {
            'timeout_hours': 72
        }
        
        # Execute activity
        result = await self.workflow.request_approvals(self.mock_context)
        
        # Verify
        assert result['request_count'] == 2
        assert len(result['approval_requests']) == 2
        assert result['timeout_scheduled'] is True
        
        # Check approvals created
        from business_modules.investment.models import DealApproval
        approvals = DealApproval.objects.filter(deal=self.deal)
        assert approvals.count() == 2
        
        # Check notifications sent
        assert mock_notif.send_notification.call_count == 2
    
    async def test_collect_approvals_activity(self):
        """Test approval collection activity."""
        # Create approvals
        from business_modules.investment.models import DealApproval
        
        approval1 = DealApproval.objects.create(
            deal=self.deal,
            approver=self.users['manager'],
            approval_type='manager',
            status='approved'
        )
        
        approval2 = DealApproval.objects.create(
            deal=self.deal,
            approver=self.users['director'],
            approval_type='director',
            status='pending'
        )
        
        # Set context
        self.context_data['approval_requests'] = [
            str(approval1.id),
            str(approval2.id)
        ]
        self.context_data['approval_requirements'] = {
            'required_roles': ['manager', 'director']
        }
        
        # Mock wait for signal
        self.mock_context.wait_for_signal = AsyncMock()
        
        # Execute activity
        result = await self.workflow.collect_approvals(self.mock_context)
        
        # Verify
        assert result['all_approved'] is False  # Director pending
        assert result['any_rejected'] is False
        assert result['approved_roles'] == ['manager']
        assert result['pending_roles'] == ['director']
    
    @patch('business_modules.investment.workflows.deal_approval.notification_service')
    async def test_finalize_approval_success(self, mock_notif):
        """Test successful deal approval finalization."""
        # Set context for approval
        self.context_data['all_approved'] = True
        self.context_data['any_rejected'] = False
        self.context_data['approved_roles'] = ['manager', 'director']
        
        # Mock deal service
        with patch.object(self.workflow.deal_service, 'transition_stage') as mock_transition:
            mock_transition.return_value = (True, 'Transitioned to negotiation')
            
            # Execute activity
            result = await self.workflow.finalize_approval(self.mock_context)
        
        # Verify
        assert result['approved'] is True
        assert result['new_stage'] == 'negotiation'
        assert 'Deal approved successfully' in result['message']
        
        # Check notifications sent to team
        mock_notif.send_notification.assert_called()
    
    async def test_handle_approval_timeout(self):
        """Test approval timeout handling."""
        # Create pending approval
        from business_modules.investment.models import DealApproval
        
        approval = DealApproval.objects.create(
            deal=self.deal,
            approver=self.users['manager'],
            approval_type='manager',
            status='pending'
        )
        
        # Create manager for escalation
        self.users['manager'].manager = self.users['director']
        self.users['manager'].save()
        
        # Execute timeout handler
        await self.workflow._handle_approval_timeout(
            self.mock_context,
            {
                'approval_id': str(approval.id),
                'approver': {
                    'user_id': str(self.users['manager'].id),
                    'name': 'Manager User',
                    'role': 'manager'
                }
            }
        )
        
        # Check escalation created
        escalated = DealApproval.objects.filter(
            deal=self.deal,
            approval_type='manager_escalated'
        ).first()
        assert escalated is not None
        assert escalated.approver == self.users['director']


class TestAssessmentReviewWorkflow(TestCase):
    """Test assessment review workflow."""
    
    def setUp(self):
        """Set up test environment."""
        self.workflow = AssessmentReviewWorkflow()
        
        # Create test partner and assessment
        from business_modules.investment.models import (
            DevelopmentPartner, AssessmentTemplate
        )
        
        self.partner = DevelopmentPartner.objects.create(
            name='Test Partner',
            sector='technology'
        )
        
        self.template = AssessmentTemplate.objects.create(
            name='Standard Assessment',
            code='standard',
            version='1.0',
            scoring_config={
                'section_weights': {
                    'technical': 0.4,
                    'financial': 0.3,
                    'operational': 0.3
                }
            }
        )
        
        self.assessment = Assessment.objects.create(
            partner=self.partner,
            template=self.template,
            title='Test Assessment',
            status='submitted'
        )
        
        # Create test user (reviewer)
        self.reviewer = User.objects.create_user(
            username='reviewer',
            email='reviewer@test.com',
            password='testpass123'
        )
        
        # Mock context
        self.mock_context = Mock(spec=WorkflowContext)
        self.mock_context.get.side_effect = self._context_get
        self.mock_context.update.return_value = None
        self.mock_context.set_status.return_value = None
        self.mock_context.started_at = timezone.now()
        
        # Context data
        self.context_data = {
            'assessment_id': str(self.assessment.id),
            'initiated_by': str(self.reviewer.id)
        }
    
    def _context_get(self, key, default=None):
        """Mock context.get() method."""
        return self.context_data.get(key, default)
    
    async def test_validate_submission_activity(self):
        """Test assessment submission validation."""
        # Create assessment sections and questions
        from business_modules.investment.models import (
            AssessmentSection, AssessmentQuestion, AssessmentResponse
        )
        
        section = AssessmentSection.objects.create(
            assessment=self.assessment,
            name='Technical',
            is_required=True
        )
        
        question = AssessmentQuestion.objects.create(
            section=section,
            question_text='Describe your technology stack',
            question_type='text',
            is_required=True
        )
        
        # Add response
        AssessmentResponse.objects.create(
            assessment=self.assessment,
            question=question,
            response_value='Modern cloud-based architecture'
        )
        
        # Execute validation
        result = await self.workflow.validate_submission(self.mock_context)
        
        # Verify
        assert result['is_valid'] is True
        assert result['completion_rate'] == 100.0
        assert len(result['validation_issues']) == 0
    
    @patch('business_modules.investment.services.assessment.AssessmentServiceImpl')
    async def test_calculate_scores_activity(self, mock_service_class):
        """Test score calculation activity."""
        # Configure mock
        mock_service = mock_service_class.return_value
        mock_service.calculate_scores.return_value = {
            'overall': 82.5,
            'technical': 85.0,
            'financial': 80.0,
            'operational': 82.5
        }
        mock_service.get_benchmarks.return_value = {
            'available': True,
            'percentiles': [
                {'percentile': 25, 'score': 65},
                {'percentile': 50, 'score': 75},
                {'percentile': 75, 'score': 85},
                {'percentile': 90, 'score': 92}
            ]
        }
        
        # Execute activity
        result = await self.workflow.calculate_scores(self.mock_context)
        
        # Verify
        assert result['overall_score'] == 82.5
        assert result['review_type'] == 'expedited'  # Score > 70
        assert result['review_path'] == 'manual'
        assert result['percentile_rank'] == 75  # Score 82.5 is in 75th percentile
    
    async def test_auto_approval_path(self):
        """Test automatic approval for high scores."""
        # Set high score
        self.context_data['overall_score'] = 90.0
        self.context_data['review_type'] = 'auto_approve'
        self.context_data['review_path'] = 'automatic'
        self.context_data['section_scores'] = {'overall': 90.0}
        
        # Execute routing
        result = await self.workflow.route_for_review(self.mock_context)
        
        # Verify
        assert result['routed'] is True
        assert result['reviewer_id'] == 'system'
        assert result['auto_decided'] is True
        assert result['decision'] == 'approve'
        
        # Check automatic review created
        from business_modules.investment.models import AssessmentReview
        review = AssessmentReview.objects.filter(
            assessment=self.assessment
        ).first()
        assert review is not None
        assert review.decision == 'approve'
        assert review.reviewer is None  # System review
    
    @patch('business_modules.investment.workflows.assessment_review.notification_service')
    async def test_manual_review_assignment(self, mock_notif):
        """Test manual review assignment."""
        # Create reviewer with permissions
        from django.contrib.auth.models import Group
        reviewer_group = Group.objects.create(name='assessment_reviewer_analyst')
        self.reviewer.groups.add(reviewer_group)
        
        # Set medium score for manual review
        self.context_data['overall_score'] = 75.0
        self.context_data['review_type'] = 'standard'
        self.context_data['review_path'] = 'manual'
        
        # Execute routing
        result = await self.workflow.route_for_review(self.mock_context)
        
        # Verify
        assert result['routed'] is True
        assert result['reviewer_id'] == str(self.reviewer.id)
        assert result['auto_decided'] is False
        assert result['timeout_hours'] == 48  # Standard review timeout
        
        # Check notification sent
        mock_notif.send_notification.assert_called_once()
        notif_call = mock_notif.send_notification.call_args
        assert notif_call[1]['user_id'] == str(self.reviewer.id)
        assert notif_call[1]['type'] == 'assessment_review'


class TestPartnerOnboardingWorkflow(TransactionTestCase):
    """Test partner onboarding workflow."""
    
    def setUp(self):
        """Set up test environment."""
        self.workflow = PartnerOnboardingWorkflow()
        
        # Create test lead
        self.lead = Lead.objects.create(
            company_name='OnboardingCo',
            contact_name='John Onboard',
            contact_email='john@onboarding.com',
            contact_phone='+1234567890',
            sector='technology',
            status='qualified',
            score=85.0
        )
        
        # Create test user
        self.user = User.objects.create_user(
            username='onboarding_user',
            email='onboard@test.com',
            password='testpass123'
        )
        
        # Mock context
        self.mock_context = Mock(spec=WorkflowContext)
        self.mock_context.get.side_effect = self._context_get
        self.mock_context.update.return_value = None
        self.mock_context.set_status.return_value = None
        self.mock_context.started_at = timezone.now()
        
        # Context data
        self.context_data = {
            'lead_id': str(self.lead.id),
            'initiated_by': str(self.user.id)
        }
    
    def _context_get(self, key, default=None):
        """Mock context.get() method."""
        return self.context_data.get(key, default)
    
    async def test_convert_lead_activity(self):
        """Test lead to partner conversion."""
        # Execute conversion
        result = await self.workflow.convert_lead(self.mock_context)
        
        # Verify
        assert 'partner_id' in result
        assert result['partner_name'] == 'OnboardingCo'
        assert result['checklist_created'] is True
        assert result['checklist_items'] > 0
        
        # Check database
        self.lead.refresh_from_db()
        assert self.lead.status == 'converted'
        assert self.lead.converted_date is not None
        assert self.lead.converted_to_partner is not None
        
        # Check partner created
        partner = self.lead.converted_to_partner
        assert partner.name == 'OnboardingCo'
        assert partner.sector == 'technology'
        assert partner.onboarding_status == 'in_progress'
        
        # Check checklist created
        from business_modules.investment.models import OnboardingChecklistItem
        checklist = OnboardingChecklistItem.objects.filter(partner=partner)
        assert checklist.count() > 0
    
    @patch('business_modules.investment.workflows.partner_onboarding.notification_service')
    async def test_document_collection_activity(self, mock_notif):
        """Test document collection process."""
        # Create partner
        partner = DevelopmentPartner.objects.create(
            name='DocTestPartner',
            sector='technology'
        )
        
        # Create primary contact
        from business_modules.investment.models import PartnerContact
        contact = PartnerContact.objects.create(
            partner=partner,
            name='Doc Contact',
            email='doc@partner.com',
            is_primary=True,
            user=self.user
        )
        
        # Set context
        self.context_data['partner_id'] = str(partner.id)
        
        # Mock wait for signal with timeout
        async def mock_wait(signal, timeout):
            return False  # Simulate timeout
        self.mock_context.wait_for_signal_or_timeout = mock_wait
        
        # Execute activity
        result = await self.workflow.collect_documents(self.mock_context)
        
        # Verify
        assert 'documents_collected' in result
        assert 'missing_documents' in result
        assert result['all_collected'] is False
        
        # Check notification sent
        mock_notif.send_notification.assert_called()
        notif_call = mock_notif.send_notification.call_args
        assert notif_call[1]['type'] == 'document_request'
    
    @patch('business_modules.investment.workflows.partner_onboarding.notification_service')
    @patch('platform_core.notifications.email_service')
    async def test_setup_access_activity(self, mock_email, mock_notif):
        """Test partner access setup."""
        # Create partner
        partner = DevelopmentPartner.objects.create(
            name='AccessTestPartner',
            sector='technology'
        )
        
        # Create primary contact
        from business_modules.investment.models import PartnerContact
        contact = PartnerContact.objects.create(
            partner=partner,
            name='Access Contact',
            email='access@partner.com',
            is_primary=True
        )
        
        # Set context
        self.context_data['partner_id'] = str(partner.id)
        
        # Execute activity
        result = await self.workflow.setup_access(self.mock_context)
        
        # Verify
        assert result['access_created'] is True
        assert 'user_id' in result
        assert 'username' in result
        assert result['welcome_email_sent'] is True
        
        # Check user created
        from django.contrib.auth import get_user_model
        User = get_user_model()
        portal_user = User.objects.get(id=result['user_id'])
        assert portal_user.email == 'access@partner.com'
        assert portal_user.is_active is True
        
        # Check email sent
        mock_email.send_email.assert_called_once()
        email_call = mock_email.send_email.call_args
        assert email_call[1]['to'] == 'access@partner.com'
        assert email_call[1]['template'] == 'partner_welcome'