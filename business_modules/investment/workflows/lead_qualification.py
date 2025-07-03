"""
Lead Qualification Workflow

Automated lead qualification process with scoring, assignment, and follow-up.
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional
from django.utils import timezone

from platform_core.workflows import Workflow, Activity, WorkflowContext
from platform_core.workflows.decorators import activity
from platform_core.notifications import notification_service
from platform_core.cache import cache_manager
from platform_core.events import event_publisher

from business_modules.investment.services import LeadManagementServiceImpl
from business_modules.investment.models import Lead, LeadActivity

logger = logging.getLogger(__name__)


class LeadQualificationWorkflow(Workflow):
    """
    Lead qualification workflow with automated scoring and assignment.
    
    Process:
    1. Score lead using ML model
    2. Check qualification criteria
    3. Assign to appropriate team member
    4. Schedule follow-up activities
    5. Monitor progress and escalate if needed
    """
    
    def __init__(self):
        super().__init__(
            name='lead_qualification',
            version='1.0.0',
            description='Automated lead qualification and assignment'
        )
        self.lead_service = LeadManagementServiceImpl()
    
    @activity(
        name='score_lead',
        timeout=timedelta(minutes=5),
        retry_policy={'max_attempts': 3, 'backoff': 2.0}
    )
    async def score_lead(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Score lead using ML model."""
        lead_id = ctx.get('lead_id')
        
        try:
            # Score lead
            score_result = self.lead_service.score_lead(lead_id)
            
            # Log activity
            LeadActivity.objects.create(
                lead_id=lead_id,
                activity_type='scoring',
                description=f"Lead scored: {score_result['score']:.2f}",
                user_id=ctx.get('initiated_by'),
                metadata={'score_details': score_result}
            )
            
            return {
                'score': score_result['score'],
                'score_components': score_result.get('components', {}),
                'model_id': score_result.get('model_id')
            }
            
        except Exception as e:
            logger.error(f"Error scoring lead {lead_id}: {e}")
            raise
    
    @activity(
        name='check_qualification',
        timeout=timedelta(minutes=2)
    )
    async def check_qualification(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Check if lead meets qualification criteria."""
        lead_id = ctx.get('lead_id')
        score = ctx.get('score')
        
        try:
            lead = Lead.objects.get(id=lead_id)
            
            # Get qualification threshold from settings
            threshold = cache_manager.get(
                'lead_qualification_threshold',
                default=70.0
            )
            
            # Check qualification criteria
            is_qualified = score >= threshold
            
            # Additional business rules
            reasons = []
            
            if not is_qualified:
                reasons.append(f"Score {score:.1f} below threshold {threshold}")
            
            if not lead.contact_email and not lead.contact_phone:
                is_qualified = False
                reasons.append("Missing contact information")
            
            if lead.sector in ['prohibited', 'restricted']:
                is_qualified = False
                reasons.append(f"Restricted sector: {lead.sector}")
            
            # Update lead status
            if is_qualified:
                lead.status = 'qualified'
                lead.qualified_date = timezone.now()
            else:
                lead.status = 'not_qualified'
                lead.metadata['disqualification_reasons'] = reasons
            
            lead.save()
            
            # Publish event
            event_publisher.publish(
                f'lead.{"qualified" if is_qualified else "disqualified"}',
                {
                    'lead_id': str(lead_id),
                    'score': score,
                    'reasons': reasons
                }
            )
            
            return {
                'is_qualified': is_qualified,
                'reasons': reasons,
                'status': lead.status
            }
            
        except Exception as e:
            logger.error(f"Error checking qualification for lead {lead_id}: {e}")
            raise
    
    @activity(
        name='assign_lead',
        timeout=timedelta(minutes=5),
        compensation='unassign_lead'
    )
    async def assign_lead(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Assign qualified lead to team member."""
        lead_id = ctx.get('lead_id')
        is_qualified = ctx.get('is_qualified')
        
        if not is_qualified:
            return {'assigned': False, 'reason': 'Lead not qualified'}
        
        try:
            # Auto-assign lead
            assignment_result = self.lead_service.assign_lead(lead_id)
            
            if assignment_result['assigned']:
                # Send notification
                notification_service.send_notification(
                    user_id=assignment_result['assigned_to'],
                    title='New Lead Assignment',
                    message=f"You have been assigned a new qualified lead: {assignment_result['lead_name']}",
                    type='lead_assignment',
                    priority='high',
                    data={'lead_id': lead_id}
                )
                
                # Log activity
                LeadActivity.objects.create(
                    lead_id=lead_id,
                    activity_type='assignment',
                    description=f"Lead assigned to {assignment_result['assigned_to_name']}",
                    user_id=ctx.get('initiated_by'),
                    metadata={'assignment_details': assignment_result}
                )
            
            return assignment_result
            
        except Exception as e:
            logger.error(f"Error assigning lead {lead_id}: {e}")
            raise
    
    @activity(
        name='unassign_lead',
        timeout=timedelta(minutes=2)
    )
    async def unassign_lead(self, ctx: WorkflowContext) -> None:
        """Compensation: Unassign lead if workflow fails."""
        lead_id = ctx.get('lead_id')
        assigned_to = ctx.get('assigned_to')
        
        if assigned_to:
            try:
                lead = Lead.objects.get(id=lead_id)
                lead.assigned_to = None
                lead.save()
                
                logger.info(f"Unassigned lead {lead_id} from {assigned_to} (compensation)")
                
            except Exception as e:
                logger.error(f"Error unassigning lead {lead_id}: {e}")
    
    @activity(
        name='schedule_followup',
        timeout=timedelta(minutes=3)
    )
    async def schedule_followup(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Schedule follow-up activities."""
        lead_id = ctx.get('lead_id')
        assigned_to = ctx.get('assigned_to')
        
        if not assigned_to:
            return {'scheduled': False, 'reason': 'No assignee'}
        
        try:
            lead = Lead.objects.get(id=lead_id)
            
            # Schedule initial contact
            followup_date = timezone.now() + timedelta(days=1)
            
            # Create follow-up activity
            followup = LeadActivity.objects.create(
                lead=lead,
                activity_type='task',
                description='Initial contact - introduce services and assess needs',
                user_id=assigned_to,
                metadata={
                    'due_date': followup_date.isoformat(),
                    'priority': 'high',
                    'task_type': 'initial_contact'
                }
            )
            
            # Send reminder notification
            notification_service.schedule_notification(
                user_id=assigned_to,
                title='Lead Follow-up Reminder',
                message=f"Remember to contact {lead.contact_name} from {lead.company_name}",
                send_at=followup_date,
                type='lead_followup',
                data={'lead_id': str(lead_id), 'activity_id': str(followup.id)}
            )
            
            # Update lead
            lead.next_action_date = followup_date
            lead.next_action = 'Initial contact'
            lead.save()
            
            return {
                'scheduled': True,
                'followup_date': followup_date.isoformat(),
                'activity_id': str(followup.id)
            }
            
        except Exception as e:
            logger.error(f"Error scheduling follow-up for lead {lead_id}: {e}")
            raise
    
    @activity(
        name='setup_monitoring',
        timeout=timedelta(minutes=2)
    )
    async def setup_monitoring(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Setup progress monitoring and escalation."""
        lead_id = ctx.get('lead_id')
        assigned_to = ctx.get('assigned_to')
        
        try:
            # Create monitoring child workflow
            monitoring_workflow = ctx.create_child_workflow(
                'lead_progress_monitor',
                {
                    'lead_id': lead_id,
                    'assigned_to': assigned_to,
                    'check_interval_days': 3,
                    'escalation_days': 7
                }
            )
            
            # Schedule periodic checks
            ctx.schedule_signal(
                signal_name='check_progress',
                delay=timedelta(days=3),
                data={'check_number': 1}
            )
            
            return {
                'monitoring_setup': True,
                'child_workflow_id': monitoring_workflow.id
            }
            
        except Exception as e:
            logger.error(f"Error setting up monitoring for lead {lead_id}: {e}")
            raise
    
    async def execute(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Execute lead qualification workflow."""
        lead_id = ctx.get('lead_id')
        
        logger.info(f"Starting lead qualification workflow for lead {lead_id}")
        
        try:
            # Step 1: Score lead
            score_result = await self.score_lead(ctx)
            ctx.update(score_result)
            
            # Step 2: Check qualification
            qualification_result = await self.check_qualification(ctx)
            ctx.update(qualification_result)
            
            # Step 3: Assign if qualified
            if qualification_result['is_qualified']:
                assignment_result = await self.assign_lead(ctx)
                ctx.update(assignment_result)
                
                # Step 4: Schedule follow-up
                if assignment_result.get('assigned'):
                    followup_result = await self.schedule_followup(ctx)
                    ctx.update(followup_result)
                    
                    # Step 5: Setup monitoring
                    monitoring_result = await self.setup_monitoring(ctx)
                    ctx.update(monitoring_result)
            
            # Update workflow status
            ctx.set_status('completed')
            
            return {
                'lead_id': lead_id,
                'qualified': qualification_result['is_qualified'],
                'score': score_result['score'],
                'assigned_to': ctx.get('assigned_to'),
                'next_action_date': ctx.get('followup_date'),
                'workflow_duration': (
                    timezone.now() - ctx.started_at
                ).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Lead qualification workflow failed for {lead_id}: {e}")
            ctx.set_status('failed')
            raise
    
    async def handle_signal(self, ctx: WorkflowContext, signal_name: str, 
                          signal_data: Dict[str, Any]) -> None:
        """Handle workflow signals."""
        if signal_name == 'check_progress':
            await self._check_lead_progress(ctx, signal_data)
        
        elif signal_name == 'escalate':
            await self._escalate_lead(ctx, signal_data)
    
    async def _check_lead_progress(self, ctx: WorkflowContext, 
                                  data: Dict[str, Any]) -> None:
        """Check lead progress and escalate if needed."""
        lead_id = ctx.get('lead_id')
        check_number = data.get('check_number', 1)
        
        try:
            lead = Lead.objects.get(id=lead_id)
            
            # Check if lead has progressed
            recent_activities = LeadActivity.objects.filter(
                lead=lead,
                created_date__gte=timezone.now() - timedelta(days=3)
            ).count()
            
            if recent_activities == 0 and lead.status == 'qualified':
                # No progress - escalate
                ctx.send_signal('escalate', {
                    'reason': 'No activity in 3 days',
                    'check_number': check_number
                })
            
            elif lead.status in ['converted', 'lost']:
                # Lead closed - complete monitoring
                ctx.set_status('completed')
                
            else:
                # Schedule next check
                ctx.schedule_signal(
                    signal_name='check_progress',
                    delay=timedelta(days=3),
                    data={'check_number': check_number + 1}
                )
                
        except Exception as e:
            logger.error(f"Error checking progress for lead {lead_id}: {e}")
    
    async def _escalate_lead(self, ctx: WorkflowContext, 
                            data: Dict[str, Any]) -> None:
        """Escalate stalled lead."""
        lead_id = ctx.get('lead_id')
        assigned_to = ctx.get('assigned_to')
        reason = data.get('reason')
        
        try:
            # Notify manager
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            assignee = User.objects.get(id=assigned_to)
            manager = assignee.manager if hasattr(assignee, 'manager') else None
            
            if manager:
                notification_service.send_notification(
                    user_id=str(manager.id),
                    title='Lead Escalation',
                    message=f"Lead requires attention: {reason}",
                    type='lead_escalation',
                    priority='urgent',
                    data={'lead_id': lead_id, 'assigned_to': assigned_to}
                )
            
            # Log escalation
            LeadActivity.objects.create(
                lead_id=lead_id,
                activity_type='escalation',
                description=f"Lead escalated: {reason}",
                metadata={'escalation_data': data}
            )
            
            # Publish event
            event_publisher.publish('lead.escalated', {
                'lead_id': lead_id,
                'reason': reason,
                'assigned_to': assigned_to
            })
            
        except Exception as e:
            logger.error(f"Error escalating lead {lead_id}: {e}")