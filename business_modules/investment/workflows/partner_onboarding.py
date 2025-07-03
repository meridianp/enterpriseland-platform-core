"""
Partner Onboarding Workflow

End-to-end partner onboarding from lead conversion to operational setup.
"""

import logging
from datetime import timedelta
from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.db import transaction

from platform_core.workflows import Workflow, Activity, WorkflowContext
from platform_core.workflows.decorators import activity
from platform_core.workflows.saga import Saga, SagaStep
from platform_core.notifications import notification_service
from platform_core.events import event_publisher

from business_modules.investment.models import (
    Lead, DevelopmentPartner, PartnerContact, PartnerDocument
)

logger = logging.getLogger(__name__)


class PartnerOnboardingWorkflow(Workflow):
    """
    Complete partner onboarding workflow.
    
    Process:
    1. Convert qualified lead to partner
    2. Collect and verify documentation
    3. Setup partner access and accounts
    4. Conduct initial assessment
    5. Create first deal opportunity
    6. Schedule kickoff meeting
    """
    
    def __init__(self):
        super().__init__(
            name='partner_onboarding',
            version='1.0.0',
            description='End-to-end partner onboarding process'
        )
        self._init_required_documents()
    
    def _init_required_documents(self):
        """Initialize required onboarding documents."""
        self.required_documents = {
            'legal': [
                'certificate_of_incorporation',
                'articles_of_association',
                'board_resolution'
            ],
            'financial': [
                'audited_financials',
                'bank_statements',
                'tax_clearance'
            ],
            'compliance': [
                'aml_policy',
                'kyc_documentation',
                'regulatory_licenses'
            ],
            'operational': [
                'organization_chart',
                'key_personnel_cvs',
                'project_portfolio'
            ]
        }
    
    @activity(
        name='convert_lead',
        timeout=timedelta(minutes=10),
        retry_policy={'max_attempts': 2}
    )
    async def convert_lead(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Convert qualified lead to development partner."""
        lead_id = ctx.get('lead_id')
        
        try:
            lead = Lead.objects.get(id=lead_id)
            
            # Verify lead is qualified
            if lead.status != 'qualified':
                raise ValueError(f"Lead status must be 'qualified', got '{lead.status}'")
            
            with transaction.atomic():
                # Create development partner
                partner = DevelopmentPartner.objects.create(
                    name=lead.company_name,
                    sector=lead.sector,
                    description=lead.description,
                    website=lead.metadata.get('website'),
                    lead=lead,
                    onboarding_status='in_progress',
                    metadata={
                        'converted_from_lead': str(lead_id),
                        'conversion_date': timezone.now().isoformat(),
                        'lead_score': lead.score
                    }
                )
                
                # Create primary contact
                primary_contact = PartnerContact.objects.create(
                    partner=partner,
                    name=lead.contact_name,
                    email=lead.contact_email,
                    phone=lead.contact_phone,
                    is_primary=True,
                    role='Primary Contact',
                    metadata={'imported_from_lead': True}
                )
                
                # Update lead status
                lead.status = 'converted'
                lead.converted_date = timezone.now()
                lead.converted_to_partner = partner
                lead.save()
                
                # Create onboarding checklist
                checklist = self._create_onboarding_checklist(partner)
                
                # Log activity
                from business_modules.investment.models import PartnerActivity
                
                PartnerActivity.objects.create(
                    partner=partner,
                    activity_type='conversion',
                    description=f"Partner created from lead conversion",
                    user_id=ctx.get('initiated_by'),
                    metadata={
                        'lead_id': str(lead_id),
                        'checklist_items': len(checklist)
                    }
                )
                
                # Publish event
                event_publisher.publish('partner.created', {
                    'partner_id': str(partner.id),
                    'lead_id': str(lead_id),
                    'sector': partner.sector
                })
            
            return {
                'partner_id': str(partner.id),
                'partner_name': partner.name,
                'contact_id': str(primary_contact.id),
                'checklist_created': True,
                'checklist_items': len(checklist)
            }
            
        except Exception as e:
            logger.error(f"Error converting lead {lead_id}: {e}")
            raise
    
    def _create_onboarding_checklist(self, partner) -> List[Dict[str, Any]]:
        """Create onboarding checklist items."""
        from business_modules.investment.models import OnboardingChecklistItem
        
        checklist_items = []
        
        # Document collection items
        for category, documents in self.required_documents.items():
            for doc_type in documents:
                item = OnboardingChecklistItem.objects.create(
                    partner=partner,
                    category=category,
                    item_type='document',
                    name=doc_type.replace('_', ' ').title(),
                    description=f"Upload {doc_type.replace('_', ' ')}",
                    is_required=True,
                    due_date=timezone.now() + timedelta(days=14),
                    metadata={'document_type': doc_type}
                )
                checklist_items.append(item)
        
        # Setup items
        setup_items = [
            {
                'category': 'setup',
                'name': 'Create Partner Portal Account',
                'description': 'Setup access to partner portal',
                'due_days': 3
            },
            {
                'category': 'setup',
                'name': 'Assign Relationship Manager',
                'description': 'Assign dedicated relationship manager',
                'due_days': 1
            },
            {
                'category': 'setup',
                'name': 'Complete Initial Assessment',
                'description': 'Conduct initial partner assessment',
                'due_days': 21
            },
            {
                'category': 'setup',
                'name': 'Schedule Kickoff Meeting',
                'description': 'Schedule partnership kickoff meeting',
                'due_days': 7
            }
        ]
        
        for item_data in setup_items:
            item = OnboardingChecklistItem.objects.create(
                partner=partner,
                category=item_data['category'],
                item_type='task',
                name=item_data['name'],
                description=item_data['description'],
                is_required=True,
                due_date=timezone.now() + timedelta(days=item_data['due_days'])
            )
            checklist_items.append(item)
        
        return checklist_items
    
    @activity(
        name='collect_documents',
        timeout=timedelta(days=14),
        heartbeat_timeout=timedelta(hours=24)
    )
    async def collect_documents(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Collect and verify required documents."""
        partner_id = ctx.get('partner_id')
        
        try:
            partner = DevelopmentPartner.objects.get(id=partner_id)
            
            # Send document request notification
            notification_service.send_notification(
                user_id=str(partner.primary_contact.user_id),
                title='Document Upload Required',
                message='Please upload required onboarding documents',
                type='document_request',
                data={
                    'partner_id': partner_id,
                    'portal_url': f"/partners/{partner_id}/documents"
                }
            )
            
            # Wait for documents with periodic checks
            max_checks = 14  # Daily checks for 14 days
            check_count = 0
            
            while check_count < max_checks:
                # Check document status
                doc_status = self._check_document_status(partner)
                
                if doc_status['all_uploaded']:
                    break
                
                # Send reminder every 3 days
                if check_count % 3 == 0 and check_count > 0:
                    self._send_document_reminder(partner, doc_status)
                
                # Wait for signal or timeout
                signal_received = await ctx.wait_for_signal_or_timeout(
                    'documents_uploaded',
                    timeout=timedelta(days=1)
                )
                
                if signal_received:
                    break
                
                check_count += 1
            
            # Final document status
            final_status = self._check_document_status(partner)
            
            # Verify documents
            verification_results = []
            for doc in partner.documents.all():
                verified, issues = self._verify_document(doc)
                verification_results.append({
                    'document_id': str(doc.id),
                    'document_type': doc.document_type,
                    'verified': verified,
                    'issues': issues
                })
                
                if not verified:
                    # Request reupload
                    notification_service.send_notification(
                        user_id=str(partner.primary_contact.user_id),
                        title='Document Verification Failed',
                        message=f"Please reupload {doc.document_type}: {', '.join(issues)}",
                        type='document_verification_failed',
                        data={'document_id': str(doc.id)}
                    )
            
            return {
                'documents_collected': final_status['uploaded_count'],
                'documents_required': final_status['required_count'],
                'all_collected': final_status['all_uploaded'],
                'verification_results': verification_results,
                'missing_documents': final_status['missing_documents']
            }
            
        except Exception as e:
            logger.error(f"Error collecting documents for partner {partner_id}: {e}")
            raise
    
    def _check_document_status(self, partner) -> Dict[str, Any]:
        """Check current document upload status."""
        from business_modules.investment.models import OnboardingChecklistItem
        
        required_docs = OnboardingChecklistItem.objects.filter(
            partner=partner,
            item_type='document',
            is_required=True
        )
        
        uploaded_docs = PartnerDocument.objects.filter(
            partner=partner,
            status='active'
        ).values_list('document_type', flat=True)
        
        missing_docs = []
        for item in required_docs:
            doc_type = item.metadata.get('document_type')
            if doc_type and doc_type not in uploaded_docs:
                missing_docs.append(doc_type)
        
        return {
            'required_count': required_docs.count(),
            'uploaded_count': len(uploaded_docs),
            'all_uploaded': len(missing_docs) == 0,
            'missing_documents': missing_docs
        }
    
    def _verify_document(self, document) -> tuple[bool, List[str]]:
        """Verify document validity."""
        issues = []
        
        # Check file exists
        if not document.file_url:
            issues.append("File not found")
        
        # Check expiry
        if document.expiry_date and document.expiry_date < timezone.now().date():
            issues.append("Document expired")
        
        # Check file size (max 10MB)
        if document.file_size and document.file_size > 10 * 1024 * 1024:
            issues.append("File too large (max 10MB)")
        
        # Check file type
        allowed_types = ['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx']
        file_ext = document.file_url.split('.')[-1].lower()
        if file_ext not in allowed_types:
            issues.append(f"Invalid file type: {file_ext}")
        
        return len(issues) == 0, issues
    
    def _send_document_reminder(self, partner, doc_status):
        """Send document upload reminder."""
        missing_docs_str = ', '.join(doc_status['missing_documents'][:3])
        if len(doc_status['missing_documents']) > 3:
            missing_docs_str += f" and {len(doc_status['missing_documents']) - 3} more"
        
        notification_service.send_notification(
            user_id=str(partner.primary_contact.user_id),
            title='Document Upload Reminder',
            message=f"Please upload missing documents: {missing_docs_str}",
            type='document_reminder',
            priority='high',
            data={
                'partner_id': str(partner.id),
                'missing_count': len(doc_status['missing_documents'])
            }
        )
    
    @activity(
        name='setup_access',
        timeout=timedelta(minutes=30),
        compensation='revoke_access'
    )
    async def setup_access(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Setup partner portal access and accounts."""
        partner_id = ctx.get('partner_id')
        
        try:
            partner = DevelopmentPartner.objects.get(id=partner_id)
            
            # Create portal user account
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            portal_user = User.objects.create_user(
                username=f"partner_{partner.id[:8]}",
                email=partner.primary_contact.email,
                first_name=partner.primary_contact.name.split()[0],
                last_name=' '.join(partner.primary_contact.name.split()[1:]),
                is_active=True
            )
            
            # Assign partner role
            from django.contrib.auth.models import Group
            partner_group = Group.objects.get_or_create(name='partner_user')[0]
            portal_user.groups.add(partner_group)
            
            # Link contact to user
            partner.primary_contact.user = portal_user
            partner.primary_contact.save()
            
            # Generate temporary password
            temp_password = User.objects.make_random_password(length=12)
            portal_user.set_password(temp_password)
            portal_user.save()
            
            # Send welcome email with credentials
            from platform_core.notifications import email_service
            
            email_service.send_email(
                to=portal_user.email,
                subject='Welcome to EnterpriseLand Partner Portal',
                template='partner_welcome',
                context={
                    'partner_name': partner.name,
                    'contact_name': partner.primary_contact.name,
                    'username': portal_user.username,
                    'temp_password': temp_password,
                    'portal_url': 'https://partners.enterpriseland.com',
                    'support_email': 'support@enterpriseland.com'
                }
            )
            
            # Setup API access if requested
            api_access = ctx.get('enable_api_access', False)
            api_credentials = None
            
            if api_access:
                from platform_core.security import api_key_service
                
                api_key = api_key_service.create_api_key(
                    user=portal_user,
                    name=f"{partner.name} API Key",
                    scopes=['partner:read', 'partner:write'],
                    expires_in_days=365
                )
                
                api_credentials = {
                    'api_key': api_key['key'],
                    'api_secret': api_key['secret'],
                    'expires_at': api_key['expires_at']
                }
            
            # Update checklist
            from business_modules.investment.models import OnboardingChecklistItem
            
            checklist_item = OnboardingChecklistItem.objects.filter(
                partner=partner,
                name__icontains='portal account'
            ).first()
            
            if checklist_item:
                checklist_item.is_completed = True
                checklist_item.completed_date = timezone.now()
                checklist_item.completed_by = portal_user
                checklist_item.save()
            
            return {
                'access_created': True,
                'user_id': str(portal_user.id),
                'username': portal_user.username,
                'email': portal_user.email,
                'api_access': api_access,
                'api_credentials': api_credentials,
                'welcome_email_sent': True
            }
            
        except Exception as e:
            logger.error(f"Error setting up access for partner {partner_id}: {e}")
            raise
    
    @activity(
        name='revoke_access',
        timeout=timedelta(minutes=10)
    )
    async def revoke_access(self, ctx: WorkflowContext) -> None:
        """Compensation: Revoke partner access if workflow fails."""
        user_id = ctx.get('user_id')
        
        if user_id:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                
                user = User.objects.get(id=user_id)
                user.is_active = False
                user.save()
                
                logger.info(f"Revoked access for user {user_id} (compensation)")
                
            except Exception as e:
                logger.error(f"Error revoking access: {e}")
    
    @activity(
        name='assign_relationship_manager',
        timeout=timedelta(minutes=15)
    )
    async def assign_relationship_manager(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Assign dedicated relationship manager."""
        partner_id = ctx.get('partner_id')
        
        try:
            partner = DevelopmentPartner.objects.get(id=partner_id)
            
            # Find available relationship manager
            from django.contrib.auth import get_user_model
            from django.db.models import Count
            
            User = get_user_model()
            
            # Get RMs with capacity (less than 10 active partners)
            available_rms = User.objects.filter(
                is_active=True,
                groups__name='relationship_manager'
            ).annotate(
                partner_count=Count('managed_partners')
            ).filter(
                partner_count__lt=10
            ).order_by('partner_count')
            
            if not available_rms.exists():
                raise ValueError("No relationship managers available")
            
            # Assign based on sector expertise if possible
            sector_expert = available_rms.filter(
                profile__expertise_sectors__contains=partner.sector
            ).first()
            
            rm = sector_expert or available_rms.first()
            
            # Create assignment
            partner.relationship_manager = rm
            partner.rm_assigned_date = timezone.now()
            partner.save()
            
            # Send introduction email
            notification_service.send_notification(
                user_id=str(partner.primary_contact.user_id),
                title='Your Relationship Manager',
                message=f"{rm.get_full_name()} has been assigned as your relationship manager",
                type='rm_assignment',
                data={
                    'rm_id': str(rm.id),
                    'rm_name': rm.get_full_name(),
                    'rm_email': rm.email,
                    'rm_phone': rm.profile.phone if hasattr(rm, 'profile') else None
                }
            )
            
            # Notify RM
            notification_service.send_notification(
                user_id=str(rm.id),
                title='New Partner Assignment',
                message=f"You have been assigned as RM for {partner.name}",
                type='partner_assignment',
                priority='high',
                data={
                    'partner_id': str(partner_id),
                    'partner_name': partner.name,
                    'sector': partner.sector
                }
            )
            
            # Update checklist
            from business_modules.investment.models import OnboardingChecklistItem
            
            checklist_item = OnboardingChecklistItem.objects.filter(
                partner=partner,
                name__icontains='relationship manager'
            ).first()
            
            if checklist_item:
                checklist_item.is_completed = True
                checklist_item.completed_date = timezone.now()
                checklist_item.completed_by = rm
                checklist_item.save()
            
            return {
                'rm_assigned': True,
                'rm_id': str(rm.id),
                'rm_name': rm.get_full_name(),
                'rm_email': rm.email,
                'is_sector_expert': rm == sector_expert
            }
            
        except Exception as e:
            logger.error(f"Error assigning RM for partner {partner_id}: {e}")
            raise
    
    @activity(
        name='create_initial_assessment',
        timeout=timedelta(minutes=20)
    )
    async def create_initial_assessment(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Create initial partner assessment."""
        partner_id = ctx.get('partner_id')
        
        try:
            # Start assessment workflow
            assessment_workflow = ctx.create_child_workflow(
                'assessment_creation',
                {
                    'partner_id': partner_id,
                    'template': 'initial_partner_assessment',
                    'auto_assign': True,
                    'priority': 'high'
                }
            )
            
            # Update checklist
            from business_modules.investment.models import OnboardingChecklistItem
            
            partner = DevelopmentPartner.objects.get(id=partner_id)
            
            checklist_item = OnboardingChecklistItem.objects.filter(
                partner=partner,
                name__icontains='initial assessment'
            ).first()
            
            if checklist_item:
                checklist_item.metadata['assessment_workflow_id'] = str(assessment_workflow.id)
                checklist_item.save()
            
            return {
                'assessment_initiated': True,
                'workflow_id': str(assessment_workflow.id),
                'template': 'initial_partner_assessment'
            }
            
        except Exception as e:
            logger.error(f"Error creating assessment for partner {partner_id}: {e}")
            raise
    
    @activity(
        name='create_first_deal',
        timeout=timedelta(minutes=15)
    )
    async def create_first_deal(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Create first deal opportunity."""
        partner_id = ctx.get('partner_id')
        
        try:
            partner = DevelopmentPartner.objects.get(id=partner_id)
            
            # Create pipeline deal
            from business_modules.investment.models import Deal, DealType
            
            deal_type = DealType.objects.get_or_create(
                name='Partnership Deal',
                defaults={
                    'description': 'Standard partnership deal',
                    'workflow_config': {'stages': ['pipeline', 'qualification', 'negotiation']}
                }
            )[0]
            
            deal = Deal.objects.create(
                title=f"{partner.name} - Initial Partnership",
                deal_type=deal_type,
                partner=partner,
                description=f"Initial partnership opportunity with {partner.name}",
                status='pipeline',
                created_by_id=ctx.get('initiated_by'),
                metadata={
                    'onboarding_deal': True,
                    'partner_sector': partner.sector
                }
            )
            
            # Add RM as team member
            if partner.relationship_manager:
                from business_modules.investment.models import DealTeamMember
                
                DealTeamMember.objects.create(
                    deal=deal,
                    user=partner.relationship_manager,
                    role='lead',
                    can_edit=True,
                    can_approve=True
                )
            
            # Start deal workflow
            deal_workflow = ctx.create_child_workflow(
                'deal_pipeline',
                {
                    'deal_id': str(deal.id),
                    'auto_advance': False,
                    'priority': 'normal'
                }
            )
            
            deal.workflow_instance_id = deal_workflow.id
            deal.save()
            
            return {
                'deal_created': True,
                'deal_id': str(deal.id),
                'deal_title': deal.title,
                'workflow_id': str(deal_workflow.id)
            }
            
        except Exception as e:
            logger.error(f"Error creating deal for partner {partner_id}: {e}")
            raise
    
    @activity(
        name='schedule_kickoff',
        timeout=timedelta(minutes=10)
    )
    async def schedule_kickoff(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Schedule partnership kickoff meeting."""
        partner_id = ctx.get('partner_id')
        rm_id = ctx.get('rm_id')
        
        try:
            partner = DevelopmentPartner.objects.get(id=partner_id)
            
            # Schedule meeting for next week
            meeting_date = timezone.now() + timedelta(days=7)
            
            # Find next weekday
            while meeting_date.weekday() >= 5:  # Skip weekend
                meeting_date += timedelta(days=1)
            
            # Create calendar event
            from business_modules.investment.models import Meeting
            
            meeting = Meeting.objects.create(
                title=f"Partnership Kickoff - {partner.name}",
                meeting_type='kickoff',
                scheduled_date=meeting_date.replace(hour=10, minute=0, second=0),
                duration_minutes=60,
                location='Video Conference',
                partner=partner,
                organized_by_id=rm_id,
                metadata={
                    'agenda': [
                        'Welcome and introductions',
                        'Partnership overview and objectives',
                        'Platform walkthrough',
                        'Initial opportunities discussion',
                        'Next steps and timeline'
                    ],
                    'attendees': [
                        {'type': 'internal', 'id': rm_id},
                        {'type': 'partner', 'id': str(partner.primary_contact.id)}
                    ]
                }
            )
            
            # Send calendar invites
            from platform_core.integrations import calendar_service
            
            calendar_event = calendar_service.create_event(
                title=meeting.title,
                start_time=meeting.scheduled_date,
                duration_minutes=meeting.duration_minutes,
                attendees=[
                    partner.primary_contact.email,
                    partner.relationship_manager.email
                ],
                description=f"Partnership kickoff meeting for {partner.name}",
                location=meeting.location
            )
            
            meeting.calendar_event_id = calendar_event['id']
            meeting.save()
            
            # Update checklist
            from business_modules.investment.models import OnboardingChecklistItem
            
            checklist_item = OnboardingChecklistItem.objects.filter(
                partner=partner,
                name__icontains='kickoff meeting'
            ).first()
            
            if checklist_item:
                checklist_item.is_completed = True
                checklist_item.completed_date = timezone.now()
                checklist_item.metadata['meeting_id'] = str(meeting.id)
                checklist_item.save()
            
            return {
                'meeting_scheduled': True,
                'meeting_id': str(meeting.id),
                'meeting_date': meeting.scheduled_date.isoformat(),
                'calendar_event_id': calendar_event['id']
            }
            
        except Exception as e:
            logger.error(f"Error scheduling kickoff for partner {partner_id}: {e}")
            raise
    
    @activity(
        name='finalize_onboarding',
        timeout=timedelta(minutes=10)
    )
    async def finalize_onboarding(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Finalize onboarding and mark partner as active."""
        partner_id = ctx.get('partner_id')
        
        try:
            partner = DevelopmentPartner.objects.get(id=partner_id)
            
            # Check all required items completed
            from business_modules.investment.models import OnboardingChecklistItem
            
            incomplete_items = OnboardingChecklistItem.objects.filter(
                partner=partner,
                is_required=True,
                is_completed=False
            )
            
            if incomplete_items.exists():
                incomplete_names = list(incomplete_items.values_list('name', flat=True))
                logger.warning(f"Incomplete onboarding items: {incomplete_names}")
            
            # Update partner status
            partner.onboarding_status = 'completed'
            partner.onboarding_completed_date = timezone.now()
            partner.is_active = True
            partner.save()
            
            # Send completion notification
            notification_service.send_notification(
                user_id=str(partner.primary_contact.user_id),
                title='Welcome to EnterpriseLand!',
                message='Your onboarding is complete. Welcome to our partnership!',
                type='onboarding_complete',
                data={
                    'partner_id': str(partner_id),
                    'dashboard_url': f"/partners/{partner_id}/dashboard"
                }
            )
            
            # Notify internal team
            notification_service.send_notification(
                user_id=str(partner.relationship_manager_id),
                title='Partner Onboarding Complete',
                message=f"{partner.name} has completed onboarding",
                type='onboarding_complete_internal',
                data={'partner_id': str(partner_id)}
            )
            
            # Publish event
            event_publisher.publish('partner.onboarded', {
                'partner_id': str(partner_id),
                'partner_name': partner.name,
                'sector': partner.sector,
                'onboarding_duration_days': (
                    partner.onboarding_completed_date - partner.created_date
                ).days
            })
            
            return {
                'onboarding_complete': True,
                'partner_active': partner.is_active,
                'duration_days': (
                    partner.onboarding_completed_date - partner.created_date
                ).days,
                'incomplete_items': len(incomplete_items)
            }
            
        except Exception as e:
            logger.error(f"Error finalizing onboarding for partner {partner_id}: {e}")
            raise
    
    async def execute(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Execute partner onboarding workflow."""
        lead_id = ctx.get('lead_id')
        
        logger.info(f"Starting partner onboarding workflow for lead {lead_id}")
        
        try:
            # Step 1: Convert lead to partner
            conversion_result = await self.convert_lead(ctx)
            ctx.update(conversion_result)
            
            # Step 2: Collect documents
            doc_result = await self.collect_documents(ctx)
            ctx.update(doc_result)
            
            # Step 3: Setup access
            access_result = await self.setup_access(ctx)
            ctx.update(access_result)
            
            # Step 4: Assign relationship manager
            rm_result = await self.assign_relationship_manager(ctx)
            ctx.update(rm_result)
            
            # Step 5: Create initial assessment
            assessment_result = await self.create_initial_assessment(ctx)
            ctx.update(assessment_result)
            
            # Step 6: Create first deal
            deal_result = await self.create_first_deal(ctx)
            ctx.update(deal_result)
            
            # Step 7: Schedule kickoff meeting
            kickoff_result = await self.schedule_kickoff(ctx)
            ctx.update(kickoff_result)
            
            # Step 8: Finalize onboarding
            final_result = await self.finalize_onboarding(ctx)
            ctx.update(final_result)
            
            # Update workflow status
            ctx.set_status('completed')
            
            return {
                'lead_id': lead_id,
                'partner_id': ctx.get('partner_id'),
                'partner_name': ctx.get('partner_name'),
                'onboarding_complete': True,
                'rm_assigned': ctx.get('rm_name'),
                'portal_access': ctx.get('username'),
                'first_deal_id': ctx.get('deal_id'),
                'kickoff_date': ctx.get('meeting_date'),
                'duration': (timezone.now() - ctx.started_at).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Partner onboarding workflow failed for lead {lead_id}: {e}")
            ctx.set_status('failed')
            raise
    
    async def handle_signal(self, ctx: WorkflowContext, signal_name: str,
                          signal_data: Dict[str, Any]) -> None:
        """Handle workflow signals."""
        if signal_name == 'documents_uploaded':
            # Continue document collection
            ctx.send_signal('continue_collection', signal_data)
        
        elif signal_name == 'expedite_onboarding':
            # Fast-track remaining steps
            ctx.update({'expedited': True})


class PartnerOnboardingSaga(Saga):
    """
    Saga for complex partner onboarding across multiple systems.
    
    Ensures consistency across CRM, ERP, and partner systems.
    """
    
    def __init__(self):
        super().__init__(
            name='partner_onboarding_saga',
            version='1.0.0',
            description='Coordinate partner onboarding across systems'
        )
    
    @SagaStep(
        name='create_crm_account',
        compensation='delete_crm_account'
    )
    async def create_crm_account(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Create partner account in CRM system."""
        # Implementation for CRM account creation
        return {'crm_account_id': 'CRM123'}
    
    @SagaStep(
        name='create_erp_account',
        compensation='delete_erp_account'
    )
    async def create_erp_account(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Create partner account in ERP system."""
        # Implementation for ERP account creation
        return {'erp_account_id': 'ERP456'}
    
    @SagaStep(
        name='provision_resources',
        compensation='deprovision_resources'
    )
    async def provision_resources(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Provision partner resources (storage, compute, etc)."""
        # Implementation for resource provisioning
        return {'resources_provisioned': True}