"""
Investment Module Service Interfaces

Defines the public interfaces for investment module services.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from django.db.models import QuerySet


class MarketIntelligenceService(ABC):
    """
    Market intelligence service interface.
    
    Provides news discovery, target identification, and market analytics.
    """
    
    @abstractmethod
    def discover_news(self, query_templates: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Discover news articles based on query templates.
        
        Args:
            query_templates: Optional list of specific templates to use
            
        Returns:
            List of discovered news articles
        """
        pass
    
    @abstractmethod
    def identify_targets(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Identify potential target companies from news articles.
        
        Args:
            articles: List of news articles to analyze
            
        Returns:
            List of identified target companies
        """
        pass
    
    @abstractmethod
    def score_target(self, target: Dict[str, Any]) -> float:
        """
        Score a target company based on investment criteria.
        
        Args:
            target: Target company data
            
        Returns:
            Score between 0 and 100
        """
        pass
    
    @abstractmethod
    def get_market_trends(self, sector: Optional[str] = None, 
                         period: str = 'month') -> Dict[str, Any]:
        """
        Get market trends and analytics.
        
        Args:
            sector: Optional sector filter
            period: Time period (day, week, month, year)
            
        Returns:
            Market trends data
        """
        pass
    
    @abstractmethod
    def track_competitor(self, competitor_id: str) -> Dict[str, Any]:
        """
        Track competitor activities and news.
        
        Args:
            competitor_id: Competitor identifier
            
        Returns:
            Competitor tracking data
        """
        pass


class LeadManagementService(ABC):
    """
    Lead management service interface.
    
    Provides lead scoring, workflow automation, and pipeline management.
    """
    
    @abstractmethod
    def create_lead(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new lead.
        
        Args:
            data: Lead data
            
        Returns:
            Created lead
        """
        pass
    
    @abstractmethod
    def score_lead(self, lead_id: str, model_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Score a lead using ML models.
        
        Args:
            lead_id: Lead identifier
            model_id: Optional specific model to use
            
        Returns:
            Scoring results with score and components
        """
        pass
    
    @abstractmethod
    def qualify_lead(self, lead_id: str) -> Tuple[bool, str]:
        """
        Qualify a lead for follow-up.
        
        Args:
            lead_id: Lead identifier
            
        Returns:
            Tuple of (qualified, reason)
        """
        pass
    
    @abstractmethod
    def assign_lead(self, lead_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Assign lead to user or auto-assign.
        
        Args:
            lead_id: Lead identifier
            user_id: Optional user to assign to
            
        Returns:
            Assignment details
        """
        pass
    
    @abstractmethod
    def get_pipeline_analytics(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get lead pipeline analytics.
        
        Args:
            filters: Optional filters
            
        Returns:
            Pipeline analytics data
        """
        pass
    
    @abstractmethod
    def process_overdue_leads(self) -> List[Dict[str, Any]]:
        """
        Process and flag overdue leads.
        
        Returns:
            List of processed overdue leads
        """
        pass


class DealWorkspaceService(ABC):
    """
    Deal workspace service interface.
    
    Provides deal lifecycle management and collaboration features.
    """
    
    @abstractmethod
    def create_deal(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new deal.
        
        Args:
            data: Deal data
            
        Returns:
            Created deal
        """
        pass
    
    @abstractmethod
    def transition_stage(self, deal_id: str, target_stage: str, 
                        user_id: str) -> Tuple[bool, str]:
        """
        Transition deal to new stage.
        
        Args:
            deal_id: Deal identifier
            target_stage: Target stage
            user_id: User performing transition
            
        Returns:
            Tuple of (success, message)
        """
        pass
    
    @abstractmethod
    def add_team_member(self, deal_id: str, user_id: str, 
                       role: str) -> Dict[str, Any]:
        """
        Add team member to deal.
        
        Args:
            deal_id: Deal identifier
            user_id: User to add
            role: Team member role
            
        Returns:
            Team member details
        """
        pass
    
    @abstractmethod
    def create_milestone(self, deal_id: str, milestone_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create deal milestone.
        
        Args:
            deal_id: Deal identifier
            milestone_data: Milestone details
            
        Returns:
            Created milestone
        """
        pass
    
    @abstractmethod
    def generate_ic_pack(self, deal_id: str, template: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate Investment Committee pack.
        
        Args:
            deal_id: Deal identifier
            template: Optional template name
            
        Returns:
            Generated IC pack details
        """
        pass
    
    @abstractmethod
    def schedule_meeting(self, deal_id: str, meeting_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Schedule deal-related meeting.
        
        Args:
            deal_id: Deal identifier
            meeting_data: Meeting details
            
        Returns:
            Scheduled meeting details
        """
        pass


class AssessmentService(ABC):
    """
    Assessment service interface.
    
    Provides partner assessment and evaluation capabilities.
    """
    
    @abstractmethod
    def create_assessment(self, partner_id: str, template: str) -> Dict[str, Any]:
        """
        Create new assessment for partner.
        
        Args:
            partner_id: Partner identifier
            template: Assessment template
            
        Returns:
            Created assessment
        """
        pass
    
    @abstractmethod
    def submit_assessment(self, assessment_id: str, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Submit assessment for review.
        
        Args:
            assessment_id: Assessment identifier
            data: Assessment data
            
        Returns:
            Tuple of (success, message)
        """
        pass
    
    @abstractmethod
    def review_assessment(self, assessment_id: str, reviewer_id: str, 
                         decision: str, comments: str) -> Dict[str, Any]:
        """
        Review submitted assessment.
        
        Args:
            assessment_id: Assessment identifier
            reviewer_id: Reviewer user ID
            decision: Review decision (approve/reject/request_changes)
            comments: Review comments
            
        Returns:
            Review details
        """
        pass
    
    @abstractmethod
    def calculate_scores(self, assessment_id: str) -> Dict[str, float]:
        """
        Calculate assessment scores.
        
        Args:
            assessment_id: Assessment identifier
            
        Returns:
            Score breakdown by category
        """
        pass
    
    @abstractmethod
    def generate_report(self, assessment_id: str, format: str = 'pdf') -> bytes:
        """
        Generate assessment report.
        
        Args:
            assessment_id: Assessment identifier
            format: Report format (pdf, docx, html)
            
        Returns:
            Report file bytes
        """
        pass
    
    @abstractmethod
    def get_benchmarks(self, sector: str, assessment_type: str) -> Dict[str, Any]:
        """
        Get sector benchmarks for comparison.
        
        Args:
            sector: Business sector
            assessment_type: Type of assessment
            
        Returns:
            Benchmark data
        """
        pass