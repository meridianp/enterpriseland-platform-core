"""
Deal Workspace Service Implementation

Collaborative deal management with workflow automation.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from django_fsm import TransitionNotAllowed

from platform_core.cache import cache_result, cache_manager, Presence
from platform_core.events import event_publisher, saga_manager
from platform_core.websocket import websocket_manager
from platform_core.workflows import workflow_engine
from business_modules.investment.interfaces import DealWorkspaceService

logger = logging.getLogger(__name__)


class DealWorkspaceServiceImpl(DealWorkspaceService):
    """
    Implementation of deal workspace service.
    
    Features FSM workflows, real-time collaboration, and document management.
    """
    
    def __init__(self):
        """Initialize service."""
        self.cache_prefix = "deals"
        self.presence = Presence(timeout=300)  # 5 minute presence timeout
        self._init_workflow_engine()
    
    def _init_workflow_engine(self):
        """Initialize workflow configurations."""
        try:
            from business_modules.investment.models import DealType, WorkflowTemplate
            
            # Load workflow templates
            self.workflow_templates = {
                deal_type.code: deal_type.workflow_template
                for deal_type in DealType.objects.all()
                if deal_type.workflow_template
            }
        except Exception as e:
            logger.warning(f"Could not load workflow templates: {e}")
            self.workflow_templates = {}
    
    @transaction.atomic
    def create_deal(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new deal with workflow initialization.
        
        Sets up team, milestones, and starts workflow.
        """
        from business_modules.investment.models import (
            Deal, DealTeamMember, DealMilestone, DealActivity
        )
        
        try:
            # Create deal
            deal = Deal.objects.create(
                title=data['title'],
                deal_type_id=data['deal_type_id'],
                lead_id=data.get('lead_id'),
                partner_id=data.get('partner_id'),
                description=data.get('description'),
                target_close_date=data.get('target_close_date'),
                deal_size=data.get('deal_size', 0),
                currency=data.get('currency', 'USD'),
                metadata=data.get('metadata', {}),
                created_by_id=data['created_by_id'],
                group_id=data['group_id']
            )
            
            # Add creator as team member
            DealTeamMember.objects.create(
                deal=deal,
                user_id=data['created_by_id'],
                role='lead',
                can_edit=True,
                can_approve=True
            )
            
            # Add additional team members
            for member_data in data.get('team_members', []):
                DealTeamMember.objects.create(
                    deal=deal,
                    user_id=member_data['user_id'],
                    role=member_data.get('role', 'member'),
                    can_edit=member_data.get('can_edit', False),
                    can_approve=member_data.get('can_approve', False)
                )
            
            # Create initial milestones based on deal type
            self._create_initial_milestones(deal)
            
            # Create initial activity
            DealActivity.objects.create(
                deal=deal,
                activity_type='created',
                description='Deal created',
                user_id=data['created_by_id'],
                metadata={'deal_type': deal.deal_type.name}
            )
            
            # Start workflow
            workflow_instance = workflow_engine.start_workflow(
                f'deal_{deal.deal_type.code}',
                {
                    'deal_id': str(deal.id),
                    'deal_type': deal.deal_type.code,
                    'team_members': [str(tm.user_id) for tm in deal.team_members.all()]
                }
            )
            
            deal.workflow_instance_id = workflow_instance.id
            deal.save()
            
            # Start saga for complex deal orchestration
            if deal.deal_size > 10000000:  # Large deals
                saga = saga_manager.start_saga(
                    'large_deal_orchestration',
                    {
                        'deal_id': str(deal.id),
                        'deal_size': deal.deal_size,
                        'stages': ['due_diligence', 'legal_review', 'financial_review', 'approval']
                    }
                )
                deal.saga_id = saga.id
                deal.save()
            
            # Publish event
            event_data = {
                'deal_id': str(deal.id),
                'title': deal.title,
                'deal_type': deal.deal_type.code,
                'created_by_id': str(deal.created_by_id),
                'team_size': deal.team_members.count()
            }
            
            event_publisher.publish('deal.created', event_data)
            
            # Send WebSocket notification
            websocket_manager.send_to_channel(
                'deal-updates',
                {
                    'type': 'deal.created',
                    'data': event_data
                }
            )
            
            # Notify team members
            self._notify_team_members(
                deal,
                'New Deal Assignment',
                f'You have been added to deal: {deal.title}'
            )
            
            logger.info(f"Created deal {deal.id} with workflow")
            
            return {
                'id': str(deal.id),
                'title': deal.title,
                'status': deal.get_status_display(),
                'current_stage': deal.current_stage,
                'workflow_instance_id': str(workflow_instance.id),
                'team_size': deal.team_members.count(),
                'milestone_count': deal.milestones.count()
            }
            
        except Exception as e:
            logger.error(f"Error creating deal: {e}")
            raise
    
    def _create_initial_milestones(self, deal):
        """Create initial milestones based on deal type."""
        from business_modules.investment.models import DealMilestone
        
        # Get milestone templates for deal type
        templates = deal.deal_type.milestone_templates
        
        if not templates:
            # Default milestones
            templates = [
                {'name': 'Initial Review', 'stage': 'initial_review', 'blocking': True, 'order': 1},
                {'name': 'Due Diligence', 'stage': 'due_diligence', 'blocking': True, 'order': 2},
                {'name': 'Legal Review', 'stage': 'legal_review', 'blocking': False, 'order': 3},
                {'name': 'IC Approval', 'stage': 'approval', 'blocking': True, 'order': 4},
                {'name': 'Documentation', 'stage': 'documentation', 'blocking': True, 'order': 5},
                {'name': 'Closing', 'stage': 'closing', 'blocking': True, 'order': 6}
            ]
        
        for template in templates:
            DealMilestone.objects.create(
                deal=deal,
                name=template['name'],
                stage=template['stage'],
                is_blocking=template.get('blocking', False),
                order=template.get('order', 0),
                target_date=timezone.now() + timedelta(
                    days=template.get('duration_days', 30)
                )
            )
    
    def transition_stage(self, deal_id: str, target_stage: str, 
                        user_id: str) -> Tuple[bool, str]:
        """
        Transition deal to new stage with validation.
        
        Uses Django FSM for state management.
        """
        from business_modules.investment.models import Deal, DealActivity, DealTransition
        
        try:
            deal = Deal.objects.select_for_update().get(id=deal_id)
            
            # Check user permission
            if not deal.team_members.filter(
                user_id=user_id,
                can_approve=True
            ).exists():
                return False, "User does not have approval permission"
            
            # Validate transition
            available_transitions = deal.get_available_status_transitions()
            
            if target_stage not in [t.name for t in available_transitions]:
                return False, f"Invalid transition from {deal.current_stage} to {target_stage}"
            
            # Check blocking milestones
            blocking_incomplete = deal.milestones.filter(
                stage=deal.current_stage,
                is_blocking=True,
                completed_date__isnull=True
            ).exists()
            
            if blocking_incomplete:
                return False, "Blocking milestones not completed"
            
            # Record transition
            transition = DealTransition.objects.create(
                deal=deal,
                from_stage=deal.current_stage,
                to_stage=target_stage,
                transitioned_by_id=user_id,
                reason=f"Transition to {target_stage}"
            )
            
            # Execute FSM transition
            old_stage = deal.current_stage
            
            if target_stage == 'due_diligence':
                deal.start_due_diligence()
            elif target_stage == 'negotiation':
                deal.start_negotiation()
            elif target_stage == 'documentation':
                deal.start_documentation()
            elif target_stage == 'closing':
                deal.start_closing()
            elif target_stage == 'completed':
                deal.complete()
            elif target_stage == 'rejected':
                deal.reject()
            
            deal.save()
            
            # Create activity
            DealActivity.objects.create(
                deal=deal,
                activity_type='stage_changed',
                description=f'Deal moved from {old_stage} to {target_stage}',
                user_id=user_id,
                metadata={
                    'from_stage': old_stage,
                    'to_stage': target_stage,
                    'transition_id': str(transition.id)
                }
            )
            
            # Update workflow
            if deal.workflow_instance_id:
                workflow_engine.signal_workflow(
                    str(deal.workflow_instance_id),
                    'stage_changed',
                    {
                        'from_stage': old_stage,
                        'to_stage': target_stage,
                        'user_id': user_id
                    }
                )
            
            # Update saga if exists
            if deal.saga_id:
                saga_manager.advance_saga(
                    str(deal.saga_id),
                    target_stage,
                    {'transitioned_by': user_id}
                )
            
            # Invalidate cache
            cache_manager.invalidate_tag(f'deal:{deal_id}')
            
            # Publish event
            event_publisher.publish(
                'deal.stage_changed',
                {
                    'deal_id': deal_id,
                    'from_stage': old_stage,
                    'to_stage': target_stage,
                    'transitioned_by_id': user_id
                }
            )
            
            # Real-time notification
            websocket_manager.send_to_channel(
                'deal-updates',
                {
                    'type': 'deal.stage_changed',
                    'data': {
                        'deal_id': deal_id,
                        'title': deal.title,
                        'from_stage': old_stage,
                        'to_stage': target_stage
                    }
                }
            )
            
            # Notify team
            self._notify_team_members(
                deal,
                'Deal Stage Update',
                f'Deal {deal.title} moved to {target_stage}'
            )
            
            return True, f"Successfully transitioned to {target_stage}"
            
        except TransitionNotAllowed as e:
            return False, f"Transition not allowed: {str(e)}"
        except Exception as e:
            logger.error(f"Error transitioning deal {deal_id}: {e}")
            return False, str(e)
    
    def add_team_member(self, deal_id: str, user_id: str, 
                       role: str) -> Dict[str, Any]:
        """
        Add team member to deal with permissions.
        
        Updates presence tracking.
        """
        from business_modules.investment.models import Deal, DealTeamMember, DealActivity
        from django.contrib.auth import get_user_model
        
        User = get_user_model()
        
        try:
            deal = Deal.objects.get(id=deal_id)
            user = User.objects.get(id=user_id)
            
            # Check if already a member
            if deal.team_members.filter(user_id=user_id).exists():
                raise ValueError("User already a team member")
            
            # Define role permissions
            role_permissions = {
                'lead': {'can_edit': True, 'can_approve': True},
                'analyst': {'can_edit': True, 'can_approve': False},
                'reviewer': {'can_edit': False, 'can_approve': True},
                'observer': {'can_edit': False, 'can_approve': False}
            }
            
            permissions = role_permissions.get(role, {'can_edit': False, 'can_approve': False})
            
            # Add team member
            team_member = DealTeamMember.objects.create(
                deal=deal,
                user=user,
                role=role,
                **permissions
            )
            
            # Create activity
            DealActivity.objects.create(
                deal=deal,
                activity_type='team_member_added',
                description=f'{user.get_full_name()} added as {role}',
                user=user,
                metadata={'role': role}
            )
            
            # Grant access to deal documents
            self._grant_document_access(deal, user)
            
            # Send notification
            from platform_core.notifications import notification_service
            notification_service.send_notification(
                user_id=user_id,
                title='Added to Deal',
                message=f'You have been added to deal: {deal.title} as {role}',
                type='deal_assignment',
                data={'deal_id': deal_id, 'role': role}
            )
            
            # Update presence
            self.presence.set_active(
                f'deal:{deal_id}:user:{user_id}',
                metadata={
                    'user_name': user.get_full_name(),
                    'role': role,
                    'location': 'deal_workspace'
                }
            )
            
            # Publish event
            event_publisher.publish(
                'deal.team_member_added',
                {
                    'deal_id': deal_id,
                    'user_id': user_id,
                    'role': role
                }
            )
            
            return {
                'team_member_id': str(team_member.id),
                'user': {
                    'id': user_id,
                    'name': user.get_full_name(),
                    'email': user.email
                },
                'role': role,
                'permissions': permissions,
                'added_date': timezone.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error adding team member to deal {deal_id}: {e}")
            raise
    
    def _grant_document_access(self, deal, user):
        """Grant user access to deal documents."""
        # This would integrate with document management system
        pass
    
    @cache_result(timeout=300, tags=['deal_milestones'])
    def create_milestone(self, deal_id: str, milestone_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create deal milestone with dependencies.
        
        Cached with tag-based invalidation.
        """
        from business_modules.investment.models import Deal, DealMilestone, DealActivity
        
        try:
            deal = Deal.objects.get(id=deal_id)
            
            # Create milestone
            milestone = DealMilestone.objects.create(
                deal=deal,
                name=milestone_data['name'],
                description=milestone_data.get('description'),
                stage=milestone_data.get('stage', deal.current_stage),
                is_blocking=milestone_data.get('is_blocking', False),
                target_date=milestone_data.get('target_date'),
                assigned_to_id=milestone_data.get('assigned_to_id'),
                order=milestone_data.get('order', 99)
            )
            
            # Add dependencies
            for dep_id in milestone_data.get('depends_on', []):
                milestone.dependencies.add(dep_id)
            
            # Create activity
            DealActivity.objects.create(
                deal=deal,
                activity_type='milestone_created',
                description=f'Milestone created: {milestone.name}',
                metadata={
                    'milestone_id': str(milestone.id),
                    'is_blocking': milestone.is_blocking
                }
            )
            
            # Update workflow
            if deal.workflow_instance_id:
                workflow_engine.signal_workflow(
                    str(deal.workflow_instance_id),
                    'milestone_added',
                    {
                        'milestone_id': str(milestone.id),
                        'name': milestone.name,
                        'is_blocking': milestone.is_blocking
                    }
                )
            
            # Publish event
            event_publisher.publish(
                'deal.milestone_created',
                {
                    'deal_id': deal_id,
                    'milestone_id': str(milestone.id),
                    'name': milestone.name,
                    'is_blocking': milestone.is_blocking,
                    'target_date': milestone.target_date.isoformat() if milestone.target_date else None
                }
            )
            
            return {
                'id': str(milestone.id),
                'name': milestone.name,
                'stage': milestone.stage,
                'is_blocking': milestone.is_blocking,
                'target_date': milestone.target_date.isoformat() if milestone.target_date else None,
                'assigned_to_id': str(milestone.assigned_to_id) if milestone.assigned_to_id else None,
                'dependency_count': milestone.dependencies.count()
            }
            
        except Exception as e:
            logger.error(f"Error creating milestone for deal {deal_id}: {e}")
            raise
    
    def generate_ic_pack(self, deal_id: str, template: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate Investment Committee pack with all deal information.
        
        Creates comprehensive document package.
        """
        from business_modules.investment.models import Deal, DealDocument
        from platform_core.files import file_service
        import json
        
        try:
            deal = Deal.objects.select_related(
                'deal_type', 'lead', 'partner'
            ).prefetch_related(
                'team_members__user',
                'milestones',
                'activities',
                'documents'
            ).get(id=deal_id)
            
            # Determine template
            template_name = template or deal.deal_type.ic_template or 'standard'
            
            # Gather all deal data
            ic_data = {
                'deal': {
                    'id': str(deal.id),
                    'title': deal.title,
                    'type': deal.deal_type.name,
                    'stage': deal.current_stage,
                    'size': deal.deal_size,
                    'currency': deal.currency,
                    'irr': deal.irr,
                    'target_close_date': deal.target_close_date.isoformat() if deal.target_close_date else None,
                    'created_date': deal.created_date.isoformat()
                },
                'partner': self._get_partner_summary(deal.partner) if deal.partner else None,
                'lead': self._get_lead_summary(deal.lead) if deal.lead else None,
                'team': [
                    {
                        'name': tm.user.get_full_name(),
                        'role': tm.role,
                        'email': tm.user.email
                    }
                    for tm in deal.team_members.all()
                ],
                'milestones': [
                    {
                        'name': m.name,
                        'stage': m.stage,
                        'completed': m.completed_date is not None,
                        'target_date': m.target_date.isoformat() if m.target_date else None
                    }
                    for m in deal.milestones.order_by('order')
                ],
                'financial_summary': self._get_financial_summary(deal),
                'risk_assessment': self._get_risk_assessment(deal),
                'recommendations': self._get_recommendations(deal),
                'timeline': self._get_deal_timeline(deal),
                'documents': [
                    {
                        'name': doc.name,
                        'type': doc.document_type,
                        'uploaded_date': doc.uploaded_date.isoformat()
                    }
                    for doc in deal.documents.all()
                ]
            }
            
            # Generate document
            ic_pack_content = self._render_ic_template(template_name, ic_data)
            
            # Save as PDF
            pdf_content = self._generate_pdf(ic_pack_content)
            
            # Upload to storage
            file_obj = file_service.upload_file(
                file_content=pdf_content,
                filename=f'IC_Pack_{deal.title}_{timezone.now().strftime("%Y%m%d")}.pdf',
                content_type='application/pdf',
                metadata={
                    'deal_id': deal_id,
                    'document_type': 'ic_pack',
                    'template': template_name
                }
            )
            
            # Create document record
            ic_document = DealDocument.objects.create(
                deal=deal,
                name=f'IC Pack - {timezone.now().strftime("%Y-%m-%d")}',
                document_type='ic_pack',
                file_id=file_obj.id,
                uploaded_by_id=deal.created_by_id,  # System generated
                metadata={
                    'template': template_name,
                    'generated_date': timezone.now().isoformat()
                }
            )
            
            # Create activity
            DealActivity.objects.create(
                deal=deal,
                activity_type='ic_pack_generated',
                description='Investment Committee pack generated',
                metadata={
                    'document_id': str(ic_document.id),
                    'template': template_name
                }
            )
            
            # Publish event
            event_publisher.publish(
                'deal.ic_pack_generated',
                {
                    'deal_id': deal_id,
                    'document_id': str(ic_document.id),
                    'file_url': file_obj.url
                }
            )
            
            return {
                'document_id': str(ic_document.id),
                'file_id': str(file_obj.id),
                'file_url': file_obj.url,
                'filename': file_obj.filename,
                'size': file_obj.size,
                'generated_date': timezone.now().isoformat(),
                'template': template_name
            }
            
        except Exception as e:
            logger.error(f"Error generating IC pack for deal {deal_id}: {e}")
            raise
    
    def _get_partner_summary(self, partner):
        """Get partner summary for IC pack."""
        return {
            'name': partner.name,
            'sector': partner.sector,
            'description': partner.description[:500] if partner.description else None
        }
    
    def _get_lead_summary(self, lead):
        """Get lead summary for IC pack."""
        return {
            'company': lead.company_name,
            'sector': lead.sector,
            'score': lead.score,
            'source': lead.source
        }
    
    def _get_financial_summary(self, deal):
        """Get financial summary for IC pack."""
        return {
            'deal_size': deal.deal_size,
            'currency': deal.currency,
            'irr': deal.irr,
            'equity_percentage': deal.metadata.get('equity_percentage'),
            'valuation': deal.metadata.get('valuation')
        }
    
    def _get_risk_assessment(self, deal):
        """Get risk assessment for IC pack."""
        # This would perform actual risk analysis
        return {
            'overall_risk': 'Medium',
            'market_risk': 'Low',
            'execution_risk': 'Medium',
            'financial_risk': 'Low'
        }
    
    def _get_recommendations(self, deal):
        """Get recommendations for IC pack."""
        return {
            'recommendation': 'Proceed with investment',
            'conditions': [
                'Complete technical due diligence',
                'Finalize legal structure',
                'Obtain board approval'
            ]
        }
    
    def _get_deal_timeline(self, deal):
        """Get deal timeline for IC pack."""
        from business_modules.investment.models import DealActivity
        
        activities = DealActivity.objects.filter(
            deal=deal,
            activity_type__in=['created', 'stage_changed', 'milestone_completed']
        ).order_by('created_date')
        
        return [
            {
                'date': a.created_date.isoformat(),
                'event': a.description,
                'type': a.activity_type
            }
            for a in activities
        ]
    
    def _render_ic_template(self, template_name, data):
        """Render IC pack template with data."""
        # This would use a template engine
        return f"IC Pack for {data['deal']['title']}"
    
    def _generate_pdf(self, content):
        """Generate PDF from content."""
        # This would use a PDF generation library
        return b"PDF content"
    
    def schedule_meeting(self, deal_id: str, meeting_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Schedule deal-related meeting with calendar integration.
        
        Sends invites and creates tasks.
        """
        from business_modules.investment.models import Deal, DealMeeting, DealActivity
        
        try:
            deal = Deal.objects.get(id=deal_id)
            
            # Create meeting
            meeting = DealMeeting.objects.create(
                deal=deal,
                title=meeting_data['title'],
                description=meeting_data.get('description'),
                meeting_type=meeting_data.get('type', 'general'),
                scheduled_date=meeting_data['scheduled_date'],
                duration_minutes=meeting_data.get('duration_minutes', 60),
                location=meeting_data.get('location'),
                is_virtual=meeting_data.get('is_virtual', True),
                meeting_url=meeting_data.get('meeting_url'),
                organized_by_id=meeting_data['organized_by_id']
            )
            
            # Add attendees
            for attendee_id in meeting_data.get('attendee_ids', []):
                meeting.attendees.add(attendee_id)
            
            # Create calendar events
            calendar_events = []
            for attendee in meeting.attendees.all():
                # This would integrate with calendar service
                event = self._create_calendar_event(meeting, attendee)
                calendar_events.append(event)
            
            # Create activity
            DealActivity.objects.create(
                deal=deal,
                activity_type='meeting_scheduled',
                description=f'Meeting scheduled: {meeting.title}',
                user_id=meeting.organized_by_id,
                metadata={
                    'meeting_id': str(meeting.id),
                    'meeting_type': meeting.meeting_type,
                    'scheduled_date': meeting.scheduled_date.isoformat()
                }
            )
            
            # Create tasks for preparation
            if meeting.meeting_type == 'ic_review':
                workflow_engine.create_task(
                    'prepare_ic_materials',
                    {
                        'deal_id': deal_id,
                        'meeting_id': str(meeting.id),
                        'due_date': meeting.scheduled_date - timedelta(days=2)
                    }
                )
            
            # Send notifications
            for attendee in meeting.attendees.all():
                from platform_core.notifications import notification_service
                notification_service.send_notification(
                    user_id=str(attendee.id),
                    title=f'Meeting Scheduled: {meeting.title}',
                    message=f'You have been invited to a meeting for deal {deal.title}',
                    type='meeting_invite',
                    data={
                        'meeting_id': str(meeting.id),
                        'deal_id': deal_id,
                        'scheduled_date': meeting.scheduled_date.isoformat()
                    }
                )
            
            # Publish event
            event_publisher.publish(
                'deal.meeting_scheduled',
                {
                    'deal_id': deal_id,
                    'meeting_id': str(meeting.id),
                    'title': meeting.title,
                    'scheduled_date': meeting.scheduled_date.isoformat(),
                    'attendee_count': meeting.attendees.count()
                }
            )
            
            return {
                'meeting_id': str(meeting.id),
                'title': meeting.title,
                'scheduled_date': meeting.scheduled_date.isoformat(),
                'duration_minutes': meeting.duration_minutes,
                'location': meeting.location,
                'meeting_url': meeting.meeting_url,
                'attendees': [
                    {
                        'id': str(a.id),
                        'name': a.get_full_name(),
                        'email': a.email
                    }
                    for a in meeting.attendees.all()
                ],
                'calendar_events': calendar_events
            }
            
        except Exception as e:
            logger.error(f"Error scheduling meeting for deal {deal_id}: {e}")
            raise
    
    def _create_calendar_event(self, meeting, attendee):
        """Create calendar event for attendee."""
        # This would integrate with calendar service (Google Calendar, Outlook, etc.)
        return {
            'event_id': 'mock_event_123',
            'attendee_id': str(attendee.id),
            'status': 'created'
        }
    
    def _notify_team_members(self, deal, subject, message):
        """Send notification to all team members."""
        from platform_core.notifications import notification_service
        
        for team_member in deal.team_members.all():
            notification_service.send_notification(
                user_id=str(team_member.user_id),
                title=subject,
                message=message,
                type='deal_update',
                data={'deal_id': str(deal.id)}
            )