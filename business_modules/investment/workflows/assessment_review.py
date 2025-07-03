"""
Assessment Review Workflow

Automated assessment review process with scoring and decision routing.
"""

import logging
from datetime import timedelta
from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.db import transaction

from platform_core.workflows import Workflow, Activity, WorkflowContext
from platform_core.workflows.decorators import activity
from platform_core.notifications import notification_service
from platform_core.events import event_publisher
from platform_core.cache import cache_manager

from business_modules.investment.services import AssessmentServiceImpl
from business_modules.investment.models import (
    Assessment, AssessmentReview, AssessmentActivity
)

logger = logging.getLogger(__name__)


class AssessmentReviewWorkflow(Workflow):
    """
    Assessment review workflow with automated scoring and routing.
    
    Process:
    1. Initial validation and scoring
    2. Route to appropriate reviewer based on score/type
    3. Collect review decision
    4. Handle appeals if requested
    5. Finalize and generate reports
    """
    
    def __init__(self):
        super().__init__(
            name='assessment_review',
            version='1.0.0',
            description='Automated assessment review and decision process'
        )
        self.assessment_service = AssessmentServiceImpl()
        self._init_review_thresholds()
    
    def _init_review_thresholds(self):
        """Initialize review thresholds and routing rules."""
        self.review_thresholds = {
            'auto_approve': 85.0,      # Auto-approve if score >= 85
            'auto_reject': 40.0,       # Auto-reject if score < 40
            'expedited_review': 70.0,  # Expedited review if score >= 70
            'detailed_review': 55.0    # Detailed review if score >= 55
        }
        
        self.review_types = {
            'expedited': {
                'timeout_hours': 24,
                'reviewer_level': 'senior_analyst'
            },
            'standard': {
                'timeout_hours': 48,
                'reviewer_level': 'analyst'
            },
            'detailed': {
                'timeout_hours': 72,
                'reviewer_level': 'manager'
            }
        }
    
    @activity(
        name='validate_submission',
        timeout=timedelta(minutes=5),
        retry_policy={'max_attempts': 2}
    )
    async def validate_submission(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Validate assessment submission completeness."""
        assessment_id = ctx.get('assessment_id')
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            validation_issues = []
            
            # Check submission status
            if assessment.status != 'submitted':
                validation_issues.append(
                    f"Invalid status: {assessment.status}, expected 'submitted'"
                )
            
            # Check completeness
            from business_modules.investment.models import (
                AssessmentQuestion, AssessmentResponse
            )
            
            total_questions = AssessmentQuestion.objects.filter(
                section__assessment=assessment
            ).count()
            
            total_responses = AssessmentResponse.objects.filter(
                assessment=assessment
            ).count()
            
            completion_rate = (total_responses / total_questions * 100) if total_questions > 0 else 0
            
            if completion_rate < 100:
                validation_issues.append(
                    f"Incomplete responses: {completion_rate:.1f}% complete"
                )
            
            # Check required sections
            required_sections = assessment.sections.filter(
                is_required=True
            )
            
            for section in required_sections:
                section_responses = AssessmentResponse.objects.filter(
                    assessment=assessment,
                    question__section=section
                ).count()
                
                section_questions = section.questions.count()
                
                if section_responses < section_questions:
                    validation_issues.append(
                        f"Incomplete section: {section.name}"
                    )
            
            # Check submission metadata
            if not assessment.submitted_by:
                validation_issues.append("No submitter recorded")
            
            is_valid = len(validation_issues) == 0
            
            # Log validation
            AssessmentActivity.objects.create(
                assessment=assessment,
                activity_type='validation',
                description=f"Submission validation: {'Passed' if is_valid else 'Failed'}",
                user_id=ctx.get('initiated_by'),
                metadata={
                    'issues': validation_issues,
                    'completion_rate': completion_rate
                }
            )
            
            return {
                'is_valid': is_valid,
                'validation_issues': validation_issues,
                'completion_rate': completion_rate,
                'total_questions': total_questions,
                'total_responses': total_responses
            }
            
        except Exception as e:
            logger.error(f"Error validating assessment {assessment_id}: {e}")
            raise
    
    @activity(
        name='calculate_scores',
        timeout=timedelta(minutes=10)
    )
    async def calculate_scores(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Calculate assessment scores and determine review path."""
        assessment_id = ctx.get('assessment_id')
        
        try:
            # Calculate scores using service
            scores = self.assessment_service.calculate_scores(assessment_id)
            
            overall_score = scores.get('overall', 0)
            
            # Determine review type based on score
            if overall_score >= self.review_thresholds['auto_approve']:
                review_type = 'auto_approve'
                review_path = 'automatic'
            elif overall_score < self.review_thresholds['auto_reject']:
                review_type = 'auto_reject'
                review_path = 'automatic'
            elif overall_score >= self.review_thresholds['expedited_review']:
                review_type = 'expedited'
                review_path = 'manual'
            elif overall_score >= self.review_thresholds['detailed_review']:
                review_type = 'standard'
                review_path = 'manual'
            else:
                review_type = 'detailed'
                review_path = 'manual'
            
            # Get benchmarks for context
            assessment = Assessment.objects.get(id=assessment_id)
            benchmarks = self.assessment_service.get_benchmarks(
                assessment.partner.sector,
                assessment.template.code
            )
            
            # Calculate percentile ranking
            percentile = None
            if benchmarks.get('available'):
                for p in benchmarks.get('percentiles', []):
                    if overall_score >= p['score']:
                        percentile = p['percentile']
            
            # Update assessment with scores
            assessment.overall_score = overall_score
            assessment.section_scores = scores
            assessment.metadata['percentile_rank'] = percentile
            assessment.save()
            
            # Log scoring
            AssessmentActivity.objects.create(
                assessment=assessment,
                activity_type='scoring',
                description=f"Assessment scored: {overall_score:.1f}",
                user_id=ctx.get('initiated_by'),
                metadata={
                    'scores': scores,
                    'review_type': review_type,
                    'percentile': percentile
                }
            )
            
            return {
                'overall_score': overall_score,
                'section_scores': scores,
                'review_type': review_type,
                'review_path': review_path,
                'percentile_rank': percentile,
                'benchmark_available': benchmarks.get('available', False)
            }
            
        except Exception as e:
            logger.error(f"Error calculating scores for assessment {assessment_id}: {e}")
            raise
    
    @activity(
        name='route_for_review',
        timeout=timedelta(minutes=5)
    )
    async def route_for_review(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Route assessment to appropriate reviewer."""
        assessment_id = ctx.get('assessment_id')
        review_type = ctx.get('review_type')
        review_path = ctx.get('review_path')
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            if review_path == 'automatic':
                # Handle automatic decisions
                if review_type == 'auto_approve':
                    decision = 'approve'
                    reviewer_id = 'system'
                    comments = f"Automatically approved - score {ctx.get('overall_score'):.1f} exceeds threshold"
                else:  # auto_reject
                    decision = 'reject'
                    reviewer_id = 'system'
                    comments = f"Automatically rejected - score {ctx.get('overall_score'):.1f} below threshold"
                
                # Create automatic review
                review = AssessmentReview.objects.create(
                    assessment=assessment,
                    reviewer_id=None,  # System review
                    decision=decision,
                    comments=comments,
                    review_scores=ctx.get('section_scores'),
                    metadata={
                        'auto_review': True,
                        'review_type': review_type,
                        'threshold_used': self.review_thresholds.get(review_type)
                    }
                )
                
                return {
                    'routed': True,
                    'reviewer_id': reviewer_id,
                    'review_id': str(review.id),
                    'auto_decided': True,
                    'decision': decision
                }
            
            else:
                # Find appropriate reviewer
                review_config = self.review_types.get(review_type, self.review_types['standard'])
                reviewer = self._find_reviewer(
                    assessment,
                    review_config['reviewer_level']
                )
                
                if not reviewer:
                    raise ValueError(f"No reviewer available for level: {review_config['reviewer_level']}")
                
                # Assign reviewer
                assessment.assigned_reviewer = reviewer
                assessment.status = 'under_review'
                assessment.save()
                
                # Send notification
                notification_service.send_notification(
                    user_id=str(reviewer.id),
                    title=f'{review_type.title()} Assessment Review Required',
                    message=f"Assessment for {assessment.partner.name} requires {review_type} review",
                    type='assessment_review',
                    priority='high' if review_type == 'expedited' else 'normal',
                    data={
                        'assessment_id': str(assessment_id),
                        'review_type': review_type,
                        'score': ctx.get('overall_score')
                    }
                )
                
                # Schedule timeout
                ctx.schedule_signal(
                    signal_name='review_timeout',
                    delay=timedelta(hours=review_config['timeout_hours']),
                    data={
                        'reviewer_id': str(reviewer.id),
                        'review_type': review_type
                    }
                )
                
                # Log assignment
                AssessmentActivity.objects.create(
                    assessment=assessment,
                    activity_type='assignment',
                    description=f"Assigned to {reviewer.get_full_name()} for {review_type} review",
                    user_id=ctx.get('initiated_by'),
                    metadata={
                        'reviewer_id': str(reviewer.id),
                        'timeout_hours': review_config['timeout_hours']
                    }
                )
                
                return {
                    'routed': True,
                    'reviewer_id': str(reviewer.id),
                    'reviewer_name': reviewer.get_full_name(),
                    'review_type': review_type,
                    'timeout_hours': review_config['timeout_hours'],
                    'auto_decided': False
                }
            
        except Exception as e:
            logger.error(f"Error routing assessment {assessment_id}: {e}")
            raise
    
    def _find_reviewer(self, assessment, reviewer_level: str):
        """Find available reviewer based on workload and expertise."""
        from django.contrib.auth import get_user_model
        from django.db.models import Count, Q
        
        User = get_user_model()
        
        # Get reviewers with appropriate permission and level
        eligible_reviewers = User.objects.filter(
            is_active=True,
            groups__name=f'assessment_reviewer_{reviewer_level}'
        )
        
        # Filter by sector expertise if available
        if hasattr(User, 'expertise_sectors'):
            sector_experts = eligible_reviewers.filter(
                expertise_sectors__contains=assessment.partner.sector
            )
            if sector_experts.exists():
                eligible_reviewers = sector_experts
        
        # Sort by workload (least busy first)
        reviewers = eligible_reviewers.annotate(
            active_reviews=Count(
                'assigned_assessments',
                filter=Q(
                    assigned_assessments__status='under_review'
                )
            )
        ).order_by('active_reviews', '?')  # Random for tie-breaking
        
        return reviewers.first() if reviewers.exists() else None
    
    @activity(
        name='collect_review',
        timeout=timedelta(days=3),
        heartbeat_timeout=timedelta(hours=6)
    )
    async def collect_review(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Wait for and collect review decision."""
        assessment_id = ctx.get('assessment_id')
        auto_decided = ctx.get('auto_decided', False)
        
        if auto_decided:
            # Already decided automatically
            return {
                'review_collected': True,
                'decision': ctx.get('decision'),
                'auto_review': True
            }
        
        try:
            # Wait for review signal
            ctx.wait_for_signal('review_submitted')
            
            # Get latest review
            assessment = Assessment.objects.get(id=assessment_id)
            latest_review = assessment.reviews.order_by('-created_date').first()
            
            if latest_review:
                return {
                    'review_collected': True,
                    'decision': latest_review.decision,
                    'reviewer_id': str(latest_review.reviewer_id),
                    'comments': latest_review.comments,
                    'review_id': str(latest_review.id),
                    'auto_review': False
                }
            else:
                return {
                    'review_collected': False,
                    'reason': 'No review submitted'
                }
            
        except Exception as e:
            logger.error(f"Error collecting review for assessment {assessment_id}: {e}")
            raise
    
    @activity(
        name='process_decision',
        timeout=timedelta(minutes=10)
    )
    async def process_decision(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Process review decision and take appropriate actions."""
        assessment_id = ctx.get('assessment_id')
        decision = ctx.get('decision')
        reviewer_id = ctx.get('reviewer_id')
        comments = ctx.get('comments', '')
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            with transaction.atomic():
                if decision == 'approve':
                    # Approve assessment
                    assessment.status = 'approved'
                    assessment.approved_date = timezone.now()
                    assessment.approved_by_id = reviewer_id if reviewer_id != 'system' else None
                    
                    # Create partner if needed
                    from business_modules.investment.models import DevelopmentPartner
                    
                    partner = assessment.partner
                    partner.assessment_status = 'approved'
                    partner.assessment_score = assessment.overall_score
                    partner.save()
                    
                    # Generate approval certificate
                    certificate_data = self._generate_approval_certificate(assessment)
                    
                    message = "Assessment approved successfully"
                    
                elif decision == 'reject':
                    # Reject assessment
                    assessment.status = 'rejected'
                    assessment.rejected_date = timezone.now()
                    assessment.rejected_by_id = reviewer_id if reviewer_id != 'system' else None
                    assessment.rejection_reason = comments
                    
                    message = "Assessment rejected"
                    certificate_data = None
                    
                elif decision == 'request_changes':
                    # Request changes
                    assessment.status = 'changes_requested'
                    assessment.metadata['changes_requested'] = {
                        'date': timezone.now().isoformat(),
                        'reviewer_id': reviewer_id,
                        'comments': comments
                    }
                    
                    message = "Changes requested for assessment"
                    certificate_data = None
                    
                else:
                    raise ValueError(f"Invalid decision: {decision}")
                
                assessment.save()
                
                # Send notifications
                if assessment.submitted_by:
                    notification_service.send_notification(
                        user_id=str(assessment.submitted_by_id),
                        title=f"Assessment {decision.replace('_', ' ').title()}",
                        message=f"{message}. {comments[:100]}..." if comments else message,
                        type=f'assessment_{decision}',
                        data={
                            'assessment_id': str(assessment_id),
                            'decision': decision
                        }
                    )
                
                # Log decision
                AssessmentActivity.objects.create(
                    assessment=assessment,
                    activity_type='decision',
                    description=f"Assessment {decision}: {comments[:200] if comments else 'No comments'}",
                    user_id=reviewer_id if reviewer_id != 'system' else None,
                    metadata={
                        'decision': decision,
                        'auto_review': reviewer_id == 'system'
                    }
                )
                
                # Publish event
                event_publisher.publish(
                    f'assessment.{decision}',
                    {
                        'assessment_id': str(assessment_id),
                        'partner_id': str(assessment.partner_id),
                        'decision': decision,
                        'score': assessment.overall_score,
                        'reviewer_id': reviewer_id
                    }
                )
            
            return {
                'processed': True,
                'decision': decision,
                'message': message,
                'certificate_data': certificate_data,
                'final_status': assessment.status
            }
            
        except Exception as e:
            logger.error(f"Error processing decision for assessment {assessment_id}: {e}")
            raise
    
    def _generate_approval_certificate(self, assessment) -> Dict[str, Any]:
        """Generate approval certificate data."""
        return {
            'certificate_number': f"CERT-{assessment.id[:8].upper()}",
            'issued_date': timezone.now().isoformat(),
            'valid_until': (timezone.now() + timedelta(days=365)).isoformat(),
            'partner_name': assessment.partner.name,
            'assessment_type': assessment.template.name,
            'overall_score': assessment.overall_score
        }
    
    @activity(
        name='generate_report',
        timeout=timedelta(minutes=15)
    )
    async def generate_report(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Generate final assessment report."""
        assessment_id = ctx.get('assessment_id')
        decision = ctx.get('decision')
        
        if decision == 'request_changes':
            # Don't generate report for pending changes
            return {'report_generated': False, 'reason': 'Pending changes'}
        
        try:
            # Generate PDF report
            report_content = self.assessment_service.generate_report(
                assessment_id,
                format='pdf'
            )
            
            # Store report
            from platform_core.files import file_service
            
            assessment = Assessment.objects.get(id=assessment_id)
            
            file_result = file_service.store_file(
                content=report_content,
                filename=f"assessment_report_{assessment.id}.pdf",
                content_type='application/pdf',
                metadata={
                    'assessment_id': str(assessment_id),
                    'partner_id': str(assessment.partner_id),
                    'decision': decision,
                    'generated_date': timezone.now().isoformat()
                }
            )
            
            # Update assessment with report URL
            assessment.report_url = file_result['url']
            assessment.save()
            
            # Send report to stakeholders
            stakeholders = self._get_stakeholders(assessment)
            
            for stakeholder in stakeholders:
                notification_service.send_notification(
                    user_id=str(stakeholder.id),
                    title='Assessment Report Available',
                    message=f"Assessment report for {assessment.partner.name} is ready",
                    type='assessment_report',
                    data={
                        'assessment_id': str(assessment_id),
                        'report_url': file_result['url']
                    }
                )
            
            return {
                'report_generated': True,
                'report_url': file_result['url'],
                'file_id': file_result['file_id'],
                'notified_count': len(stakeholders)
            }
            
        except Exception as e:
            logger.error(f"Error generating report for assessment {assessment_id}: {e}")
            raise
    
    def _get_stakeholders(self, assessment) -> List:
        """Get list of stakeholders for assessment."""
        stakeholders = []
        
        # Submitter
        if assessment.submitted_by:
            stakeholders.append(assessment.submitted_by)
        
        # Partner team members
        if hasattr(assessment.partner, 'team_members'):
            stakeholders.extend(assessment.partner.team_members.all())
        
        # Reviewers
        for review in assessment.reviews.all():
            if review.reviewer:
                stakeholders.append(review.reviewer)
        
        return list(set(stakeholders))  # Remove duplicates
    
    async def execute(self, ctx: WorkflowContext) -> Dict[str, Any]:
        """Execute assessment review workflow."""
        assessment_id = ctx.get('assessment_id')
        
        logger.info(f"Starting assessment review workflow for {assessment_id}")
        
        try:
            # Step 1: Validate submission
            validation_result = await self.validate_submission(ctx)
            ctx.update(validation_result)
            
            if not validation_result['is_valid']:
                return {
                    'completed': False,
                    'errors': validation_result['validation_issues'],
                    'message': 'Assessment validation failed'
                }
            
            # Step 2: Calculate scores
            scores_result = await self.calculate_scores(ctx)
            ctx.update(scores_result)
            
            # Step 3: Route for review
            routing_result = await self.route_for_review(ctx)
            ctx.update(routing_result)
            
            # Step 4: Collect review
            review_result = await self.collect_review(ctx)
            ctx.update(review_result)
            
            # Step 5: Process decision
            decision_result = await self.process_decision(ctx)
            ctx.update(decision_result)
            
            # Step 6: Generate report
            report_result = await self.generate_report(ctx)
            ctx.update(report_result)
            
            # Update workflow status
            ctx.set_status('completed')
            
            return {
                'assessment_id': assessment_id,
                'completed': True,
                'decision': decision_result['decision'],
                'final_status': decision_result['final_status'],
                'overall_score': scores_result['overall_score'],
                'percentile_rank': scores_result.get('percentile_rank'),
                'report_url': report_result.get('report_url'),
                'workflow_duration': (
                    timezone.now() - ctx.started_at
                ).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Assessment review workflow failed for {assessment_id}: {e}")
            ctx.set_status('failed')
            raise
    
    async def handle_signal(self, ctx: WorkflowContext, signal_name: str,
                          signal_data: Dict[str, Any]) -> None:
        """Handle workflow signals."""
        if signal_name == 'review_submitted':
            # Continue workflow when review is submitted
            ctx.send_signal('continue_review', signal_data)
        
        elif signal_name == 'review_timeout':
            await self._handle_review_timeout(ctx, signal_data)
        
        elif signal_name == 'appeal_requested':
            await self._handle_appeal_request(ctx, signal_data)
    
    async def _handle_review_timeout(self, ctx: WorkflowContext,
                                   data: Dict[str, Any]) -> None:
        """Handle review timeout - escalate or auto-decide."""
        assessment_id = ctx.get('assessment_id')
        reviewer_id = data.get('reviewer_id')
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            if assessment.status == 'under_review':
                # Escalate to manager
                from django.contrib.auth import get_user_model
                User = get_user_model()
                
                current_reviewer = User.objects.get(id=reviewer_id)
                manager = getattr(current_reviewer, 'manager', None)
                
                if manager:
                    # Reassign to manager
                    assessment.assigned_reviewer = manager
                    assessment.save()
                    
                    # Send escalation notification
                    notification_service.send_notification(
                        user_id=str(manager.id),
                        title='Urgent: Assessment Review Escalation',
                        message=f"Assessment review escalated from {current_reviewer.get_full_name()}",
                        type='assessment_escalation',
                        priority='urgent',
                        data={'assessment_id': str(assessment_id)}
                    )
                    
                    # Log escalation
                    AssessmentActivity.objects.create(
                        assessment=assessment,
                        activity_type='escalation',
                        description=f"Review escalated from {current_reviewer.get_full_name()} due to timeout",
                        metadata={'escalation_data': data}
                    )
                else:
                    # No manager - auto-approve with note
                    ctx.send_signal('review_submitted', {
                        'decision': 'approve',
                        'reviewer_id': 'system',
                        'comments': 'Auto-approved due to review timeout and no escalation path'
                    })
            
        except Exception as e:
            logger.error(f"Error handling review timeout: {e}")
    
    async def _handle_appeal_request(self, ctx: WorkflowContext,
                                   data: Dict[str, Any]) -> None:
        """Handle appeal request for rejected assessments."""
        assessment_id = ctx.get('assessment_id')
        appeal_reason = data.get('reason')
        
        try:
            # Create appeal workflow
            appeal_workflow = ctx.create_child_workflow(
                'assessment_appeal',
                {
                    'assessment_id': assessment_id,
                    'original_decision': ctx.get('decision'),
                    'appeal_reason': appeal_reason,
                    'original_score': ctx.get('overall_score')
                }
            )
            
            logger.info(f"Appeal workflow started for assessment {assessment_id}")
            
        except Exception as e:
            logger.error(f"Error handling appeal request: {e}")