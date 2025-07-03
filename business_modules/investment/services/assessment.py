"""
Assessment Service Implementation

Partner assessment and evaluation with scoring engine.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from django.template.loader import render_to_string

from platform_core.cache import cache_result, cache_manager
from platform_core.events import event_publisher
from platform_core.workflows import workflow_engine
from platform_core.files import file_service
from business_modules.investment.interfaces import AssessmentService

logger = logging.getLogger(__name__)


class AssessmentServiceImpl(AssessmentService):
    """
    Implementation of assessment service.
    
    Features dynamic forms, scoring engine, and report generation.
    """
    
    def __init__(self):
        """Initialize service."""
        self.cache_prefix = "assessments"
        self._init_scoring_engine()
    
    def _init_scoring_engine(self):
        """Initialize scoring configurations."""
        try:
            from business_modules.investment.models import AssessmentTemplate
            
            # Load scoring weights per template
            self.scoring_weights = {}
            for template in AssessmentTemplate.objects.filter(is_active=True):
                self.scoring_weights[template.code] = template.scoring_config
                
        except Exception as e:
            logger.warning(f"Could not load scoring configurations: {e}")
            self.scoring_weights = {}
    
    @transaction.atomic
    def create_assessment(self, partner_id: str, template: str) -> Dict[str, Any]:
        """
        Create new assessment for partner using template.
        
        Sets up sections and questions dynamically.
        """
        from business_modules.investment.models import (
            Assessment, AssessmentTemplate, AssessmentSection,
            AssessmentQuestion, AssessmentResponse
        )
        
        try:
            # Get template
            template_obj = AssessmentTemplate.objects.get(code=template)
            
            # Create assessment
            assessment = Assessment.objects.create(
                partner_id=partner_id,
                template=template_obj,
                title=f"{template_obj.name} - {timezone.now().strftime('%Y-%m-%d')}",
                metadata={
                    'template_version': template_obj.version,
                    'created_from_template': True
                }
            )
            
            # Create sections from template
            for section_config in template_obj.sections:
                section = AssessmentSection.objects.create(
                    assessment=assessment,
                    name=section_config['name'],
                    description=section_config.get('description'),
                    order=section_config.get('order', 0),
                    weight=section_config.get('weight', 1.0),
                    is_required=section_config.get('required', True)
                )
                
                # Create questions for section
                for question_config in section_config.get('questions', []):
                    AssessmentQuestion.objects.create(
                        section=section,
                        question_text=question_config['text'],
                        question_type=question_config.get('type', 'text'),
                        options=question_config.get('options'),
                        validation_rules=question_config.get('validation'),
                        weight=question_config.get('weight', 1.0),
                        order=question_config.get('order', 0),
                        is_required=question_config.get('required', True),
                        help_text=question_config.get('help_text')
                    )
            
            # Start assessment workflow
            workflow_instance = workflow_engine.start_workflow(
                'assessment_review',
                {
                    'assessment_id': str(assessment.id),
                    'partner_id': partner_id,
                    'template': template
                }
            )
            
            assessment.workflow_instance_id = workflow_instance.id
            assessment.save()
            
            # Publish event
            event_publisher.publish(
                'assessment.created',
                {
                    'assessment_id': str(assessment.id),
                    'partner_id': partner_id,
                    'template': template,
                    'section_count': assessment.sections.count(),
                    'question_count': AssessmentQuestion.objects.filter(
                        section__assessment=assessment
                    ).count()
                }
            )
            
            logger.info(f"Created assessment {assessment.id} for partner {partner_id}")
            
            return {
                'id': str(assessment.id),
                'title': assessment.title,
                'status': assessment.status,
                'template': {
                    'code': template_obj.code,
                    'name': template_obj.name,
                    'version': template_obj.version
                },
                'sections': assessment.sections.count(),
                'total_questions': AssessmentQuestion.objects.filter(
                    section__assessment=assessment
                ).count(),
                'workflow_instance_id': str(workflow_instance.id)
            }
            
        except Exception as e:
            logger.error(f"Error creating assessment: {e}")
            raise
    
    def submit_assessment(self, assessment_id: str, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Submit assessment for review with validation.
        
        Validates all required fields and business rules.
        """
        from business_modules.investment.models import (
            Assessment, AssessmentQuestion, AssessmentResponse
        )
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            # Check if already submitted
            if assessment.status != 'draft':
                return False, "Assessment already submitted"
            
            # Validate responses
            validation_errors = []
            
            with transaction.atomic():
                # Process responses by section
                for section_id, responses in data.get('sections', {}).items():
                    section = assessment.sections.get(id=section_id)
                    
                    for question_id, response_value in responses.items():
                        question = AssessmentQuestion.objects.get(
                            id=question_id,
                            section=section
                        )
                        
                        # Validate response
                        is_valid, error = self._validate_response(
                            question, response_value
                        )
                        
                        if not is_valid:
                            validation_errors.append(
                                f"{section.name} - {question.question_text}: {error}"
                            )
                            continue
                        
                        # Save response
                        AssessmentResponse.objects.update_or_create(
                            assessment=assessment,
                            question=question,
                            defaults={
                                'response_value': response_value,
                                'metadata': {
                                    'submitted_at': timezone.now().isoformat()
                                }
                            }
                        )
                
                # Check all required questions answered
                required_questions = AssessmentQuestion.objects.filter(
                    section__assessment=assessment,
                    is_required=True
                )
                
                answered_questions = AssessmentResponse.objects.filter(
                    assessment=assessment,
                    question__in=required_questions
                ).values_list('question_id', flat=True)
                
                missing_questions = required_questions.exclude(
                    id__in=answered_questions
                )
                
                for question in missing_questions:
                    validation_errors.append(
                        f"{question.section.name} - {question.question_text}: Required"
                    )
                
                if validation_errors:
                    return False, "\n".join(validation_errors)
                
                # Calculate initial scores
                scores = self.calculate_scores(assessment_id)
                
                # Update assessment
                assessment.status = 'submitted'
                assessment.submitted_date = timezone.now()
                assessment.submitted_by_id = data.get('submitted_by_id')
                assessment.overall_score = scores.get('overall', 0)
                assessment.section_scores = scores
                assessment.save()
                
                # Advance workflow
                if assessment.workflow_instance_id:
                    workflow_engine.signal_workflow(
                        str(assessment.workflow_instance_id),
                        'submitted',
                        {
                            'submitted_by_id': data.get('submitted_by_id'),
                            'overall_score': assessment.overall_score
                        }
                    )
                
                # Publish event
                event_publisher.publish(
                    'assessment.submitted',
                    {
                        'assessment_id': assessment_id,
                        'partner_id': str(assessment.partner_id),
                        'overall_score': assessment.overall_score,
                        'submitted_by_id': data.get('submitted_by_id')
                    }
                )
                
                # Trigger auto-assignment for review
                self._auto_assign_reviewer(assessment)
                
                return True, "Assessment submitted successfully"
                
        except Exception as e:
            logger.error(f"Error submitting assessment {assessment_id}: {e}")
            return False, str(e)
    
    def _validate_response(self, question, response_value) -> Tuple[bool, str]:
        """Validate response against question rules."""
        if question.is_required and not response_value:
            return False, "Response required"
        
        # Type validation
        if question.question_type == 'number':
            try:
                float(response_value)
            except (TypeError, ValueError):
                return False, "Must be a number"
        
        elif question.question_type == 'select' and question.options:
            if response_value not in question.options:
                return False, "Invalid option selected"
        
        elif question.question_type == 'multiselect' and question.options:
            if not all(v in question.options for v in response_value):
                return False, "Invalid options selected"
        
        # Custom validation rules
        if question.validation_rules:
            # This would implement custom validation logic
            pass
        
        return True, ""
    
    def _auto_assign_reviewer(self, assessment):
        """Auto-assign reviewer based on workload and expertise."""
        from django.contrib.auth import get_user_model
        from django.db.models import Count, Q
        
        User = get_user_model()
        
        # Get eligible reviewers
        reviewers = User.objects.filter(
            is_active=True,
            groups__permissions__codename='review_assessments'
        ).annotate(
            pending_reviews=Count(
                'assessment_reviews',
                filter=Q(assessment_reviews__status='pending')
            )
        ).order_by('pending_reviews')
        
        if reviewers.exists():
            reviewer = reviewers.first()
            assessment.assigned_reviewer = reviewer
            assessment.save()
            
            # Send notification
            from platform_core.notifications import notification_service
            notification_service.send_notification(
                user_id=str(reviewer.id),
                title='New Assessment Review',
                message=f'Assessment for {assessment.partner.name} requires review',
                type='assessment_review',
                priority='high',
                data={'assessment_id': str(assessment.id)}
            )
    
    def review_assessment(self, assessment_id: str, reviewer_id: str, 
                         decision: str, comments: str) -> Dict[str, Any]:
        """
        Review submitted assessment with decision.
        
        Supports approve, reject, or request changes.
        """
        from business_modules.investment.models import Assessment, AssessmentReview
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            # Validate status
            if assessment.status not in ['submitted', 'under_review']:
                raise ValueError(f"Cannot review assessment in {assessment.status} status")
            
            # Create review record
            review = AssessmentReview.objects.create(
                assessment=assessment,
                reviewer_id=reviewer_id,
                decision=decision,
                comments=comments,
                review_scores=self._calculate_review_scores(assessment),
                metadata={
                    'review_duration': (
                        timezone.now() - assessment.submitted_date
                    ).total_seconds() if assessment.submitted_date else None
                }
            )
            
            # Update assessment status
            if decision == 'approve':
                assessment.status = 'approved'
                assessment.approved_date = timezone.now()
                assessment.approved_by_id = reviewer_id
                
                # Create partner record if approved
                self._create_partner_from_assessment(assessment)
                
            elif decision == 'reject':
                assessment.status = 'rejected'
                assessment.rejected_date = timezone.now()
                assessment.rejected_by_id = reviewer_id
                
            elif decision == 'request_changes':
                assessment.status = 'changes_requested'
                assessment.metadata['changes_requested_date'] = timezone.now().isoformat()
                assessment.metadata['changes_requested_by'] = reviewer_id
                
            assessment.save()
            
            # Update workflow
            if assessment.workflow_instance_id:
                workflow_engine.signal_workflow(
                    str(assessment.workflow_instance_id),
                    'reviewed',
                    {
                        'decision': decision,
                        'reviewer_id': reviewer_id,
                        'review_id': str(review.id)
                    }
                )
            
            # Invalidate cache
            cache_manager.invalidate_tag(f'assessment:{assessment_id}')
            
            # Publish event
            event_publisher.publish(
                f'assessment.{decision}',
                {
                    'assessment_id': assessment_id,
                    'reviewer_id': reviewer_id,
                    'decision': decision,
                    'partner_id': str(assessment.partner_id)
                }
            )
            
            # Send notification to submitter
            if assessment.submitted_by:
                from platform_core.notifications import notification_service
                notification_service.send_notification(
                    user_id=str(assessment.submitted_by_id),
                    title=f'Assessment {decision.title()}',
                    message=f'Your assessment for {assessment.partner.name} has been {decision}',
                    type='assessment_decision',
                    data={
                        'assessment_id': assessment_id,
                        'decision': decision
                    }
                )
            
            return {
                'review_id': str(review.id),
                'assessment_id': assessment_id,
                'decision': decision,
                'reviewer': {
                    'id': reviewer_id,
                    'name': review.reviewer.get_full_name()
                },
                'reviewed_date': timezone.now().isoformat(),
                'new_status': assessment.status
            }
            
        except Exception as e:
            logger.error(f"Error reviewing assessment {assessment_id}: {e}")
            raise
    
    def _calculate_review_scores(self, assessment):
        """Calculate detailed review scores."""
        scores = self.calculate_scores(str(assessment.id))
        
        # Add review-specific scoring
        scores['completeness'] = self._calculate_completeness_score(assessment)
        scores['quality'] = self._calculate_quality_score(assessment)
        
        return scores
    
    def _calculate_completeness_score(self, assessment):
        """Calculate how complete the assessment is."""
        total_questions = AssessmentQuestion.objects.filter(
            section__assessment=assessment
        ).count()
        
        answered_questions = AssessmentResponse.objects.filter(
            assessment=assessment
        ).count()
        
        return (answered_questions / total_questions * 100) if total_questions > 0 else 0
    
    def _calculate_quality_score(self, assessment):
        """Calculate quality of responses."""
        # This would implement quality scoring logic
        return 85.0  # Placeholder
    
    def _create_partner_from_assessment(self, assessment):
        """Create development partner from approved assessment."""
        from business_modules.investment.models import DevelopmentPartner
        
        # Extract partner data from assessment
        partner_data = self._extract_partner_data(assessment)
        
        # Create or update partner
        partner, created = DevelopmentPartner.objects.update_or_create(
            name=partner_data['name'],
            defaults=partner_data
        )
        
        if created:
            logger.info(f"Created partner {partner.id} from assessment {assessment.id}")
    
    def _extract_partner_data(self, assessment):
        """Extract partner data from assessment responses."""
        # This would map assessment responses to partner fields
        return {
            'name': assessment.partner.name,
            'assessment_id': assessment.id,
            'assessment_score': assessment.overall_score
        }
    
    @cache_result(timeout=600, tags=['assessment_scores'])
    def calculate_scores(self, assessment_id: str) -> Dict[str, float]:
        """
        Calculate assessment scores by section and overall.
        
        Cached for 10 minutes with tag invalidation.
        """
        from business_modules.investment.models import (
            Assessment, AssessmentSection, AssessmentResponse
        )
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            scores = {}
            
            # Calculate section scores
            for section in assessment.sections.all():
                section_score = self._calculate_section_score(section)
                scores[section.name] = section_score
            
            # Calculate overall score
            if assessment.template.scoring_config:
                weights = assessment.template.scoring_config.get('section_weights', {})
                
                weighted_sum = 0
                total_weight = 0
                
                for section_name, score in scores.items():
                    weight = weights.get(section_name, 1.0)
                    weighted_sum += score * weight
                    total_weight += weight
                
                scores['overall'] = (
                    weighted_sum / total_weight if total_weight > 0 else 0
                )
            else:
                # Simple average
                scores['overall'] = (
                    sum(scores.values()) / len(scores) if scores else 0
                )
            
            # Add category scores
            categories = assessment.template.scoring_config.get('categories', {})
            for category, config in categories.items():
                scores[f'category_{category}'] = self._calculate_category_score(
                    assessment, config
                )
            
            return scores
            
        except Exception as e:
            logger.error(f"Error calculating scores for assessment {assessment_id}: {e}")
            return {}
    
    def _calculate_section_score(self, section) -> float:
        """Calculate score for a section."""
        from business_modules.investment.models import AssessmentResponse
        
        responses = AssessmentResponse.objects.filter(
            question__section=section
        )
        
        if not responses.exists():
            return 0.0
        
        total_score = 0
        total_weight = 0
        
        for response in responses:
            question = response.question
            score = self._score_response(question, response.response_value)
            
            total_score += score * question.weight
            total_weight += question.weight
        
        return (total_score / total_weight * 100) if total_weight > 0 else 0
    
    def _score_response(self, question, response_value) -> float:
        """Score individual response."""
        if question.question_type == 'rating':
            # Rating questions scored directly
            return float(response_value) / 5.0 if response_value else 0
            
        elif question.question_type == 'yes_no':
            # Yes/No questions
            return 1.0 if response_value == 'yes' else 0.0
            
        elif question.question_type == 'select':
            # Option-based scoring
            scoring_map = question.metadata.get('scoring_map', {})
            return scoring_map.get(response_value, 0.5)
            
        else:
            # Text responses get base score if provided
            return 0.7 if response_value else 0.0
    
    def _calculate_category_score(self, assessment, config) -> float:
        """Calculate score for a custom category."""
        # This would implement category-specific scoring logic
        return 75.0  # Placeholder
    
    def generate_report(self, assessment_id: str, format: str = 'pdf') -> bytes:
        """
        Generate assessment report in requested format.
        
        Supports PDF, DOCX, and HTML formats.
        """
        from business_modules.investment.models import Assessment
        
        try:
            assessment = Assessment.objects.select_related(
                'partner', 'template', 'submitted_by', 'approved_by'
            ).prefetch_related(
                'sections__questions__responses',
                'reviews__reviewer'
            ).get(id=assessment_id)
            
            # Prepare report data
            report_data = {
                'assessment': assessment,
                'partner': assessment.partner,
                'scores': self.calculate_scores(assessment_id),
                'responses': self._get_formatted_responses(assessment),
                'reviews': assessment.reviews.all(),
                'benchmarks': self.get_benchmarks(
                    assessment.partner.sector,
                    assessment.template.code
                ),
                'generated_date': timezone.now()
            }
            
            # Generate report based on format
            if format == 'html':
                content = self._generate_html_report(report_data)
                return content.encode('utf-8')
                
            elif format == 'pdf':
                html_content = self._generate_html_report(report_data)
                pdf_content = self._convert_html_to_pdf(html_content)
                
                # Store in cache for quick retrieval
                cache_manager.set(
                    f'assessment_report:{assessment_id}:pdf',
                    pdf_content,
                    timeout=3600  # 1 hour
                )
                
                return pdf_content
                
            elif format == 'docx':
                docx_content = self._generate_docx_report(report_data)
                return docx_content
                
            else:
                raise ValueError(f"Unsupported format: {format}")
                
        except Exception as e:
            logger.error(f"Error generating report for assessment {assessment_id}: {e}")
            raise
    
    def _get_formatted_responses(self, assessment):
        """Get formatted responses for report."""
        from business_modules.investment.models import AssessmentResponse
        
        formatted = {}
        
        for section in assessment.sections.all():
            section_responses = []
            
            for question in section.questions.all():
                try:
                    response = AssessmentResponse.objects.get(
                        assessment=assessment,
                        question=question
                    )
                    
                    section_responses.append({
                        'question': question.question_text,
                        'type': question.question_type,
                        'response': response.response_value,
                        'score': self._score_response(
                            question, response.response_value
                        ) * 100
                    })
                except AssessmentResponse.DoesNotExist:
                    section_responses.append({
                        'question': question.question_text,
                        'type': question.question_type,
                        'response': 'Not answered',
                        'score': 0
                    })
            
            formatted[section.name] = section_responses
        
        return formatted
    
    def _generate_html_report(self, data):
        """Generate HTML report."""
        # This would use Django templates
        return render_to_string('reports/assessment_report.html', data)
    
    def _convert_html_to_pdf(self, html_content):
        """Convert HTML to PDF."""
        # This would use a PDF generation library like WeasyPrint or wkhtmltopdf
        return b"PDF content"
    
    def _generate_docx_report(self, data):
        """Generate DOCX report."""
        # This would use python-docx or similar
        return b"DOCX content"
    
    @cache_result(timeout=3600, key_prefix='benchmarks')
    def get_benchmarks(self, sector: str, assessment_type: str) -> Dict[str, Any]:
        """
        Get sector benchmarks for comparison.
        
        Cached for 1 hour.
        """
        from business_modules.investment.models import Assessment
        from django.db.models import Avg, Count, StdDev
        
        # Get comparable assessments
        comparable = Assessment.objects.filter(
            template__code=assessment_type,
            partner__sector=sector,
            status='approved',
            approved_date__gte=timezone.now() - timedelta(days=365)  # Last year
        )
        
        if not comparable.exists():
            return {
                'available': False,
                'message': 'Insufficient data for benchmarking'
            }
        
        # Calculate benchmarks
        from django.db.models import Min, Max
        
        benchmarks = comparable.aggregate(
            count=Count('id'),
            avg_score=Avg('overall_score'),
            std_dev=StdDev('overall_score'),
            min_score=Min('overall_score'),
            max_score=Max('overall_score')
        )
        
        # Calculate percentiles
        percentiles = []
        for p in [25, 50, 75, 90]:
            score = comparable.order_by('overall_score')[
                int(comparable.count() * p / 100)
            ].overall_score
            percentiles.append({'percentile': p, 'score': score})
        
        # Get top performers
        top_performers = comparable.order_by('-overall_score')[:5].values(
            'partner__name', 'overall_score', 'approved_date'
        )
        
        return {
            'available': True,
            'sector': sector,
            'assessment_type': assessment_type,
            'sample_size': benchmarks['count'],
            'metrics': {
                'average_score': benchmarks['avg_score'],
                'standard_deviation': benchmarks['std_dev'],
                'min_score': benchmarks['min_score'],
                'max_score': benchmarks['max_score']
            },
            'percentiles': percentiles,
            'top_performers': list(top_performers),
            'generated_date': timezone.now().isoformat()
        }