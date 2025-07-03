"""
Investment Module Workflows

Business process automation using platform workflow engine.
"""

from .lead_qualification import LeadQualificationWorkflow
from .deal_approval import DealApprovalWorkflow
from .assessment_review import AssessmentReviewWorkflow
from .partner_onboarding import PartnerOnboardingWorkflow

__all__ = [
    'LeadQualificationWorkflow',
    'DealApprovalWorkflow', 
    'AssessmentReviewWorkflow',
    'PartnerOnboardingWorkflow'
]