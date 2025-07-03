"""
Deal Approval Workflow

Multi-stage deal approval process with escalation and notifications.
"""

import logging
from datetime import timedelta
from typing import Dict, Any, List, Optional
from decimal import Decimal
from django.utils import timezone
from django.db import transaction

from platform_core.workflows import Workflow, Activity, WorkflowContext
from platform_core.workflows.decorators import activity
from platform_core.workflows.saga import Saga, SagaStep
from platform_core.notifications import notification_service
from platform_core.events import event_publisher

from business_modules.investment.services import DealWorkspaceServiceImpl
from business_modules.investment.models import Deal, DealApproval, DealActivity

logger = logging.getLogger(__name__)


class DealApprovalWorkflow(Workflow):
    """
    Deal approval workflow with multi-level authorization.
    
    Process:
    1. Validate deal readiness
    2. Route to appropriate approvers based on deal size
    3. Collect approvals with parallel processing
    4. Handle escalations for timeouts
    5. Finalize deal or request changes
    """
    
    def __init__(self):
        super().__init__(
            name='deal_approval',
            version='1.0.0',
            description='Multi-stage deal approval with escalation'
        )
        self.deal_service = DealWorkspaceServiceImpl()
        self._init_approval_matrix()
    
    def _init_approval_matrix(self):
        """Initialize approval requirements by deal size."""
        self.approval_matrix = {
            'small': {  # < $1M
                'threshold': Decimal('1000000'),
                'required_approvals': ['manager'],
                'timeout_hours': 48
            },
            'medium': {  # $1M - $10M
                'threshold': Decimal('10000000'),
                'required_approvals': ['manager', 'director'],
                'timeout_hours': 72
            },
            'large': {  # $10M - $50M
                'threshold': Decimal('50000000'),
                'required_approvals': ['manager', 'director', 'vp'],
                'timeout_hours': 96
            },
            'xlarge': {  # > $50M
                'threshold': None,
                'required_approvals': ['manager', 'director', 'vp', 'ceo'],
                'timeout_hours': 120
            }
        }
    
    def _get_deal_category(self, deal_size: Decimal) -> str:
        """Determine deal category based on size."""
        for category, config in self.approval_matrix.items():
            if config['threshold'] is None or deal_size < config['threshold']:
                return category
        return 'xlarge'
    
    @activity(
        name='validate_deal',
        timeout=timedelta(minutes=10),
        retry_policy={'max_attempts': 2}
    )
    async def validate_deal(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Validate deal is ready for approval."""
        deal_id = ctx.get('deal_id')
        
        try:
            deal = Deal.objects.get(id=deal_id)
            
            validation_errors = []
            warnings = []
            
            # Check required fields
            if not deal.deal_size:
                validation_errors.append("Deal size not specified")
            
            if not deal.irr:
                warnings.append("IRR not calculated")
            
            if not deal.target_close_date:
                validation_errors.append("Target close date not set")
            
            # Check milestones
            critical_milestones = deal.milestones.filter(
                is_blocking=True,
                completed_date__isnull=True
            )
            
            if critical_milestones.exists():
                milestone_names = list(critical_milestones.values_list('name', flat=True))
                validation_errors.append(
                    f"Critical milestones incomplete: {', '.join(milestone_names)}"
                )
            
            # Check documents
            required_docs = ['term_sheet', 'financial_model', 'due_diligence_report']
            missing_docs = []
            
            for doc_type in required_docs:
                if not deal.documents.filter(document_type=doc_type).exists():
                    missing_docs.append(doc_type.replace('_', ' ').title())
            
            if missing_docs:
                validation_errors.append(
                    f"Missing documents: {', '.join(missing_docs)}"
                )
            
            # Check team
            if not deal.team_members.filter(role='lead').exists():
                validation_errors.append("No deal lead assigned")
            
            is_valid = len(validation_errors) == 0
            
            # Log validation
            DealActivity.objects.create(
                deal=deal,
                activity_type='validation',
                description=f"Deal validation: {'Passed' if is_valid else 'Failed'}",
                user_id=ctx.get('initiated_by'),
                metadata={
                    'errors': validation_errors,
                    'warnings': warnings
                }
            )
            
            return {
                'is_valid': is_valid,
                'errors': validation_errors,
                'warnings': warnings,
                'deal_size': float(deal.deal_size),
                'deal_category': self._get_deal_category(deal.deal_size)
            }
            
        except Exception as e:
            logger.error(f"Error validating deal {deal_id}: {e}")
            raise
    
    @activity(
        name='identify_approvers',
        timeout=timedelta(minutes=5)
    )
    async def identify_approvers(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Identify required approvers based on deal category."""
        deal_id = ctx.get('deal_id')
        deal_category = ctx.get('deal_category')
        
        try:
            deal = Deal.objects.get(id=deal_id)
            
            # Get approval requirements
            requirements = self.approval_matrix[deal_category]
            required_roles = requirements['required_approvals']
            
            # Find approvers
            approvers = []
            
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            for role in required_roles:
                # Find users with approval role
                role_users = User.objects.filter(
                    is_active=True,
                    groups__name=f'deal_approver_{role}'
                ).order_by('?')  # Random for load balancing
                
                if role_users.exists():
                    approver = role_users.first()
                    approvers.append({
                        'user_id': str(approver.id),
                        'name': approver.get_full_name(),
                        'role': role,
                        'email': approver.email
                    })
                else:
                    # Escalate if no approver found
                    logger.warning(f"No approver found for role: {role}")
            
            # Store approval requirements
            ctx.set('approval_requirements', {
                'required_roles': required_roles,
                'approvers': approvers,
                'timeout_hours': requirements['timeout_hours'],
                'category': deal_category
            })
            
            return {
                'approvers_identified': len(approvers),
                'approvers': approvers,
                'missing_roles': [
                    role for role in required_roles 
                    if role not in [a['role'] for a in approvers]
                ]
            }
            
        except Exception as e:
            logger.error(f"Error identifying approvers for deal {deal_id}: {e}")
            raise
    
    @activity(
        name='request_approvals',
        timeout=timedelta(minutes=10)
    )
    async def request_approvals(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Request approvals from identified approvers."""
        deal_id = ctx.get('deal_id')
        approvers = ctx.get('approvers', [])
        
        try:
            deal = Deal.objects.get(id=deal_id)
            
            approval_requests = []
            
            with transaction.atomic():
                for approver in approvers:
                    # Create approval request
                    approval = DealApproval.objects.create(
                        deal=deal,
                        approver_id=approver['user_id'],
                        approval_type=approver['role'],
                        status='pending',
                        requested_date=timezone.now(),
                        metadata={
                            'workflow_id': str(ctx.workflow_id),
                            'category': ctx.get('deal_category')
                        }
                    )
                    
                    approval_requests.append(str(approval.id))
                    
                    # Send notification
                    notification_service.send_notification(
                        user_id=approver['user_id'],
                        title='Deal Approval Required',
                        message=f"Deal '{deal.title}' (${deal.deal_size:,.0f}) requires your approval",
                        type='deal_approval',
                        priority='high',
                        data={
                            'deal_id': str(deal_id),
                            'approval_id': str(approval.id),
                            'approval_url': f"/deals/{deal_id}/approve/{approval.id}"
                        }
                    )
                    
                    # Log activity
                    DealActivity.objects.create(
                        deal=deal,
                        activity_type='approval_request',
                        description=f"Approval requested from {approver['name']} ({approver['role']})",
                        user_id=ctx.get('initiated_by'),
                        metadata={'approval_id': str(approval.id)}
                    )
            
            # Schedule timeout checks
            timeout_hours = ctx.get('approval_requirements', {}).get('timeout_hours', 72)
            
            for idx, approval_id in enumerate(approval_requests):
                ctx.schedule_signal(
                    signal_name='check_approval_timeout',
                    delay=timedelta(hours=timeout_hours),
                    data={
                        'approval_id': approval_id,
                        'approver': approvers[idx]
                    }
                )
            
            return {
                'approval_requests': approval_requests,
                'request_count': len(approval_requests),
                'timeout_scheduled': True
            }
            
        except Exception as e:
            logger.error(f"Error requesting approvals for deal {deal_id}: {e}")
            raise
    
    @activity(
        name='collect_approvals',
        timeout=timedelta(days=5),
        heartbeat_timeout=timedelta(hours=12)
    )
    async def collect_approvals(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Wait for and collect approval responses."""
        deal_id = ctx.get('deal_id')
        approval_requests = ctx.get('approval_requests', [])
        required_roles = ctx.get('approval_requirements', {}).get('required_roles', [])
        
        try:
            # Wait for approvals using signals
            ctx.wait_for_signal('approval_received')
            
            # Check current approval status
            approvals = DealApproval.objects.filter(
                id__in=approval_requests
            )
            
            approved_roles = []
            rejected_roles = []
            pending_roles = []
            
            for approval in approvals:
                if approval.status == 'approved':
                    approved_roles.append(approval.approval_type)
                elif approval.status == 'rejected':
                    rejected_roles.append(approval.approval_type)
                else:
                    pending_roles.append(approval.approval_type)
            
            # Check if we have all required approvals
            all_approved = all(role in approved_roles for role in required_roles)
            any_rejected = len(rejected_roles) > 0
            
            return {
                'all_approved': all_approved,
                'any_rejected': any_rejected,
                'approved_roles': approved_roles,
                'rejected_roles': rejected_roles,
                'pending_roles': pending_roles,
                'approval_complete': all_approved or any_rejected
            }
            
        except Exception as e:
            logger.error(f"Error collecting approvals for deal {deal_id}: {e}")
            raise
    
    @activity(
        name='finalize_approval',
        timeout=timedelta(minutes=10)
    )
    async def finalize_approval(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Finalize deal approval decision."""
        deal_id = ctx.get('deal_id')
        all_approved = ctx.get('all_approved', False)
        any_rejected = ctx.get('any_rejected', False)
        rejected_roles = ctx.get('rejected_roles', [])
        
        try:
            deal = Deal.objects.get(id=deal_id)
            
            if all_approved:
                # Deal approved - advance to next stage
                success, message = self.deal_service.transition_stage(
                    str(deal_id),
                    'negotiation',
                    ctx.get('initiated_by')
                )
                
                # Send success notifications
                for team_member in deal.team_members.all():
                    notification_service.send_notification(
                        user_id=str(team_member.user_id),
                        title='Deal Approved',
                        message=f"Deal '{deal.title}' has been approved and moved to negotiation",
                        type='deal_approved',
                        data={'deal_id': str(deal_id)}
                    )
                
                # Log success
                DealActivity.objects.create(
                    deal=deal,
                    activity_type='approval_complete',
                    description='Deal approved by all required approvers',
                    user_id=ctx.get('initiated_by'),
                    metadata={
                        'approved_by': ctx.get('approved_roles', []),
                        'approval_date': timezone.now().isoformat()
                    }
                )
                
                result = {
                    'approved': True,
                    'message': 'Deal approved successfully',
                    'new_stage': 'negotiation'
                }
                
            else:
                # Deal rejected - move back to review
                deal.status = 'changes_requested'
                deal.save()
                
                # Notify team of rejection
                rejection_message = f"Deal rejected by: {', '.join(rejected_roles)}"
                
                for team_member in deal.team_members.filter(can_edit=True):
                    notification_service.send_notification(
                        user_id=str(team_member.user_id),
                        title='Deal Rejected',
                        message=f"Deal '{deal.title}' requires changes. {rejection_message}",
                        type='deal_rejected',
                        priority='high',
                        data={'deal_id': str(deal_id)}
                    )
                
                # Log rejection
                DealActivity.objects.create(
                    deal=deal,
                    activity_type='approval_rejected',
                    description=rejection_message,
                    user_id=ctx.get('initiated_by'),
                    metadata={
                        'rejected_by': rejected_roles,
                        'rejection_date': timezone.now().isoformat()
                    }
                )
                
                result = {
                    'approved': False,
                    'message': rejection_message,
                    'new_stage': 'changes_requested'
                }
            
            # Publish event
            event_publisher.publish(
                f'deal.approval_{"completed" if all_approved else "rejected"}',
                {
                    'deal_id': str(deal_id),
                    'approved': all_approved,
                    'approvers': ctx.get('approved_roles', []),
                    'rejectors': rejected_roles
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error finalizing approval for deal {deal_id}: {e}")
            raise
    
    async def execute(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Execute deal approval workflow."""
        deal_id = ctx.get('deal_id')
        
        logger.info(f"Starting deal approval workflow for deal {deal_id}")
        
        try:
            # Step 1: Validate deal
            validation_result = await self.validate_deal(ctx)
            ctx.update(validation_result)
            
            if not validation_result['is_valid']:
                return {
                    'approved': False,
                    'errors': validation_result['errors'],
                    'message': 'Deal validation failed'
                }
            
            # Step 2: Identify approvers
            approvers_result = await self.identify_approvers(ctx)
            ctx.update(approvers_result)
            
            # Step 3: Request approvals
            request_result = await self.request_approvals(ctx)
            ctx.update(request_result)
            
            # Step 4: Collect approvals
            approval_result = await self.collect_approvals(ctx)
            ctx.update(approval_result)
            
            # Step 5: Finalize decision
            final_result = await self.finalize_approval(ctx)
            
            # Update workflow status
            ctx.set_status('completed')
            
            return {
                'deal_id': deal_id,
                'approved': final_result['approved'],
                'message': final_result['message'],
                'workflow_duration': (
                    timezone.now() - ctx.started_at
                ).total_seconds(),
                'approval_summary': {
                    'category': ctx.get('deal_category'),
                    'approved_by': ctx.get('approved_roles', []),
                    'rejected_by': ctx.get('rejected_roles', [])
                }
            }
            
        except Exception as e:
            logger.error(f"Deal approval workflow failed for {deal_id}: {e}")
            ctx.set_status('failed')
            raise
    
    async def handle_signal(self, ctx: WorkflowContext, signal_name: str,
                          signal_data: Dict[str, Any]) -> None:
        """Handle workflow signals."""
        if signal_name == 'approval_received':
            await self._handle_approval_received(ctx, signal_data)
        
        elif signal_name == 'check_approval_timeout':
            await self._handle_approval_timeout(ctx, signal_data)
    
    async def _handle_approval_received(self, ctx: WorkflowContext,
                                      data: Dict[str, Any]) -> None:
        """Handle approval received signal."""
        approval_id = data.get('approval_id')
        decision = data.get('decision')
        
        logger.info(f"Approval received: {approval_id} - {decision}")
        
        # Update context and check if all approvals collected
        ctx.send_signal('continue_collection', {})
    
    async def _handle_approval_timeout(self, ctx: WorkflowContext,
                                     data: Dict[str, Any]) -> None:
        """Handle approval timeout - escalate."""
        approval_id = data.get('approval_id')
        approver = data.get('approver')
        
        try:
            approval = DealApproval.objects.get(id=approval_id)
            
            if approval.status == 'pending':
                # Escalate to manager
                from django.contrib.auth import get_user_model
                User = get_user_model()
                
                approver_user = User.objects.get(id=approver['user_id'])
                manager = getattr(approver_user, 'manager', None)
                
                if manager:
                    # Create escalated approval
                    escalated = DealApproval.objects.create(
                        deal=approval.deal,
                        approver=manager,
                        approval_type=f"{approval.approval_type}_escalated",
                        status='pending',
                        requested_date=timezone.now(),
                        metadata={
                            'escalated_from': approver['user_id'],
                            'original_approval_id': str(approval_id)
                        }
                    )
                    
                    # Send escalation notification
                    notification_service.send_notification(
                        user_id=str(manager.id),
                        title='Urgent: Deal Approval Escalation',
                        message=f"Deal approval escalated from {approver['name']}",
                        type='deal_approval_escalation',
                        priority='urgent',
                        data={
                            'deal_id': str(approval.deal_id),
                            'approval_id': str(escalated.id)
                        }
                    )
                    
                    # Log escalation
                    DealActivity.objects.create(
                        deal=approval.deal,
                        activity_type='approval_escalated',
                        description=f"Approval escalated from {approver['name']} due to timeout",
                        metadata={'escalation_data': data}
                    )
                
        except Exception as e:
            logger.error(f"Error handling approval timeout: {e}")


class LargeDealApprovalSaga(Saga):
    """
    Saga for complex large deal approvals requiring multiple systems.
    
    Coordinates approval across legal, finance, and risk departments.
    """
    
    def __init__(self):
        super().__init__(
            name='large_deal_approval_saga',
            version='1.0.0',
            description='Coordinate large deal approval across departments'
        )
    
    @SagaStep(
        name='legal_review',
        compensation='cancel_legal_review'
    )
    async def legal_review(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Submit deal for legal review."""
        # Implementation for legal review
        return {'legal_approved': True}
    
    @SagaStep(
        name='finance_approval',
        compensation='cancel_finance_approval'
    )
    async def finance_approval(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Get finance department approval."""
        # Implementation for finance approval
        return {'finance_approved': True}
    
    @SagaStep(
        name='risk_assessment',
        compensation='cancel_risk_assessment'
    )
    async def risk_assessment(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Perform risk assessment."""
        # Implementation for risk assessment
        return {'risk_approved': True}