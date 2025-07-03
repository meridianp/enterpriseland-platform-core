"""
Lead Management Service Implementation

Advanced lead scoring and workflow automation using platform services.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Count, Avg, Sum

from platform_core.cache import (
    cache_result, cache_manager, invalidate_cache,
    Counter, Leaderboard
)
from platform_core.events import event_publisher
from platform_core.websocket import websocket_manager
from platform_core.workflows import workflow_engine
from business_modules.investment.interfaces import LeadManagementService

logger = logging.getLogger(__name__)


class LeadManagementServiceImpl(LeadManagementService):
    """
    Implementation of lead management service.
    
    Features ML scoring, workflow automation, and real-time updates.
    """
    
    def __init__(self):
        """Initialize service."""
        self.cache_prefix = "leads"
        self._init_scoring_models()
        self._init_analytics()
    
    def _init_scoring_models(self):
        """Initialize scoring models."""
        try:
            from business_modules.investment.models import LeadScoringModel
            self.active_model = LeadScoringModel.objects.filter(
                is_active=True
            ).first()
        except Exception as e:
            logger.warning(f"Could not load scoring model: {e}")
            self.active_model = None
    
    def _init_analytics(self):
        """Initialize real-time analytics."""
        # Lead counters
        self.lead_counter = Counter('leads:total')
        self.qualified_counter = Counter('leads:qualified')
        self.converted_counter = Counter('leads:converted')
        
        # Lead scoring leaderboard
        self.lead_scores = Leaderboard('leads:scores')
    
    @transaction.atomic
    def create_lead(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new lead with automatic scoring.
        
        Publishes events and updates real-time counters.
        """
        from business_modules.investment.models import Lead, LeadActivity
        
        try:
            # Create lead
            lead = Lead.objects.create(
                company_name=data['company_name'],
                contact_name=data.get('contact_name'),
                contact_email=data.get('contact_email'),
                contact_phone=data.get('contact_phone'),
                source=data.get('source', 'manual'),
                sector=data.get('sector'),
                description=data.get('description'),
                metadata=data.get('metadata', {}),
                assigned_to_id=data.get('assigned_to_id'),
                group_id=data.get('group_id')
            )
            
            # Create initial activity
            LeadActivity.objects.create(
                lead=lead,
                activity_type='created',
                description='Lead created',
                user_id=data.get('created_by_id'),
                metadata={'source': data.get('source')}
            )
            
            # Auto-score if model available
            if self.active_model:
                scoring_result = self.score_lead(str(lead.id))
                lead.score = scoring_result['score']
                lead.score_components = scoring_result['components']
                lead.save()
            
            # Update counters
            self.lead_counter.increment()
            self.lead_counter.increment(window='day')
            self.lead_counter.increment(window='month')
            
            # Publish event
            event_data = {
                'lead_id': str(lead.id),
                'company_name': lead.company_name,
                'source': lead.source,
                'score': lead.score,
                'assigned_to_id': str(lead.assigned_to_id) if lead.assigned_to_id else None
            }
            
            event_publisher.publish('lead.created', event_data)
            
            # Send WebSocket notification
            websocket_manager.send_to_channel(
                'lead-activity',
                {
                    'type': 'lead.created',
                    'data': event_data
                }
            )
            
            # Check for auto-qualification
            qualified, reason = self.qualify_lead(str(lead.id))
            
            logger.info(f"Created lead {lead.id} with score {lead.score}")
            
            return {
                'id': str(lead.id),
                'company_name': lead.company_name,
                'score': lead.score,
                'status': lead.status,
                'qualified': qualified,
                'qualification_reason': reason
            }
            
        except Exception as e:
            logger.error(f"Error creating lead: {e}")
            raise
    
    @cache_result(timeout=300, tags=['lead_scoring'])
    def score_lead(self, lead_id: str, model_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Score a lead using ML models.
        
        Results cached for 5 minutes with tag-based invalidation.
        """
        from business_modules.investment.models import Lead, LeadScoringModel
        
        try:
            lead = Lead.objects.get(id=lead_id)
            
            # Get scoring model
            if model_id:
                model = LeadScoringModel.objects.get(id=model_id)
            else:
                model = self.active_model
            
            if not model:
                raise ValueError("No active scoring model")
            
            # Calculate score components
            components = {}
            
            # Business alignment
            components['business_alignment'] = self._score_business_alignment(lead)
            
            # Market presence
            components['market_presence'] = self._score_market_presence(lead)
            
            # Engagement level
            components['engagement_level'] = self._score_engagement_level(lead)
            
            # Financial indicators
            components['financial_indicators'] = self._score_financial_indicators(lead)
            
            # Strategic fit
            components['strategic_fit'] = self._score_strategic_fit(lead)
            
            # Calculate weighted score
            total_score = 0
            for component, score in components.items():
                weight = model.weights.get(component, 0.2)
                total_score += score * weight
            
            # Update lead score
            lead.score = total_score
            lead.score_components = components
            lead.scored_date = timezone.now()
            lead.scoring_model = model
            lead.save()
            
            # Update leaderboard
            self.lead_scores.add_score(f"lead:{lead_id}", total_score)
            
            # Record scoring activity
            from business_modules.investment.models import LeadActivity
            LeadActivity.objects.create(
                lead=lead,
                activity_type='scored',
                description=f'Lead scored: {total_score:.1f}',
                metadata={
                    'model_id': str(model.id),
                    'components': components
                }
            )
            
            # Publish scoring event
            event_publisher.publish(
                'lead.scored',
                {
                    'lead_id': lead_id,
                    'score': total_score,
                    'components': components,
                    'model_id': str(model.id)
                }
            )
            
            return {
                'score': total_score,
                'components': components,
                'model': {
                    'id': str(model.id),
                    'name': model.name,
                    'version': model.version
                },
                'scored_date': timezone.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error scoring lead {lead_id}: {e}")
            return {
                'score': 0,
                'components': {},
                'error': str(e)
            }
    
    def _score_business_alignment(self, lead) -> float:
        """Score business alignment based on sector and description."""
        score = 50.0  # Base score
        
        # Sector alignment
        if lead.sector in ['Technology', 'Healthcare', 'Finance']:
            score += 20
        elif lead.sector in ['Retail', 'Manufacturing']:
            score += 10
        
        # Keywords in description
        if lead.description:
            keywords = ['innovation', 'growth', 'expansion', 'technology']
            matches = sum(1 for kw in keywords if kw in lead.description.lower())
            score += matches * 5
        
        return min(score, 100)
    
    def _score_market_presence(self, lead) -> float:
        """Score market presence based on available data."""
        score = 40.0
        
        # Has website
        if lead.metadata.get('website'):
            score += 20
        
        # Employee count
        employees = lead.metadata.get('employee_count', 0)
        if employees > 100:
            score += 20
        elif employees > 50:
            score += 10
        
        # Revenue indicators
        if lead.metadata.get('revenue'):
            score += 20
        
        return min(score, 100)
    
    def _score_engagement_level(self, lead) -> float:
        """Score based on engagement activities."""
        from business_modules.investment.models import LeadActivity
        
        # Count activities
        activities = LeadActivity.objects.filter(
            lead=lead,
            created_date__gte=timezone.now() - timedelta(days=30)
        ).count()
        
        # Base score on activity count
        score = min(activities * 10, 50)
        
        # Recent activities boost
        recent = LeadActivity.objects.filter(
            lead=lead,
            created_date__gte=timezone.now() - timedelta(days=7)
        ).count()
        
        if recent > 0:
            score += 20
        
        # Response to outreach
        if LeadActivity.objects.filter(
            lead=lead,
            activity_type__in=['email_replied', 'call_answered', 'meeting_scheduled']
        ).exists():
            score += 30
        
        return min(score, 100)
    
    def _score_financial_indicators(self, lead) -> float:
        """Score financial strength."""
        score = 30.0
        
        # Revenue
        revenue = lead.metadata.get('revenue', 0)
        if revenue > 10000000:  # $10M+
            score += 30
        elif revenue > 1000000:  # $1M+
            score += 20
        elif revenue > 100000:   # $100K+
            score += 10
        
        # Growth rate
        growth = lead.metadata.get('growth_rate', 0)
        if growth > 50:
            score += 20
        elif growth > 20:
            score += 10
        
        # Funding status
        if lead.metadata.get('funded'):
            score += 20
        
        return min(score, 100)
    
    def _score_strategic_fit(self, lead) -> float:
        """Score strategic alignment."""
        score = 50.0
        
        # Geographic fit
        if lead.metadata.get('country') == 'US':
            score += 10
        
        # Partner potential
        if lead.metadata.get('partnership_interest'):
            score += 20
        
        # Technology stack alignment
        tech_match = lead.metadata.get('technology_match', 0)
        score += tech_match * 20
        
        return min(score, 100)
    
    def qualify_lead(self, lead_id: str) -> Tuple[bool, str]:
        """
        Qualify a lead for follow-up.
        
        Uses scoring threshold and business rules.
        """
        from business_modules.investment.models import Lead, LeadActivity
        
        try:
            lead = Lead.objects.get(id=lead_id)
            
            # Check if already qualified
            if lead.status in ['qualified', 'contacted', 'negotiating']:
                return True, "Already qualified"
            
            # Score threshold check
            threshold = 70.0  # Configurable
            if lead.score < threshold:
                return False, f"Score {lead.score:.1f} below threshold {threshold}"
            
            # Business rules
            if not lead.contact_email and not lead.contact_phone:
                return False, "No contact information"
            
            if lead.sector in ['Gambling', 'Tobacco']:
                return False, "Excluded sector"
            
            # Qualify the lead
            with transaction.atomic():
                lead.status = 'qualified'
                lead.qualified_date = timezone.now()
                lead.save()
                
                # Create activity
                LeadActivity.objects.create(
                    lead=lead,
                    activity_type='qualified',
                    description=f'Lead qualified with score {lead.score:.1f}',
                    metadata={'threshold': threshold}
                )
                
                # Update counter
                self.qualified_counter.increment()
                self.qualified_counter.increment(window='day')
                
                # Start qualification workflow
                workflow_engine.start_workflow(
                    'lead_qualification',
                    {
                        'lead_id': lead_id,
                        'score': lead.score,
                        'assigned_to_id': str(lead.assigned_to_id) if lead.assigned_to_id else None
                    }
                )
                
                # Publish event
                event_publisher.publish(
                    'lead.qualified',
                    {
                        'lead_id': lead_id,
                        'score': lead.score,
                        'qualified_date': timezone.now().isoformat()
                    }
                )
                
                # WebSocket notification
                websocket_manager.send_to_channel(
                    'lead-activity',
                    {
                        'type': 'lead.qualified',
                        'data': {
                            'lead_id': lead_id,
                            'company_name': lead.company_name,
                            'score': lead.score
                        }
                    }
                )
            
            return True, f"Qualified with score {lead.score:.1f}"
            
        except Exception as e:
            logger.error(f"Error qualifying lead {lead_id}: {e}")
            return False, str(e)
    
    @invalidate_cache(tags=['lead_assignment'])
    def assign_lead(self, lead_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Assign lead to user or auto-assign.
        
        Invalidates assignment cache on change.
        """
        from business_modules.investment.models import Lead, LeadActivity
        from django.contrib.auth import get_user_model
        
        User = get_user_model()
        
        try:
            lead = Lead.objects.get(id=lead_id)
            
            # Auto-assignment if no user specified
            if not user_id:
                user = self._auto_assign_user(lead)
                if not user:
                    raise ValueError("No available users for assignment")
                user_id = str(user.id)
            else:
                user = User.objects.get(id=user_id)
            
            # Assign lead
            previous_assignee = lead.assigned_to
            lead.assigned_to = user
            lead.assigned_date = timezone.now()
            lead.save()
            
            # Create activity
            LeadActivity.objects.create(
                lead=lead,
                activity_type='assigned',
                description=f'Lead assigned to {user.get_full_name() or user.username}',
                user=user,
                metadata={
                    'previous_assignee_id': str(previous_assignee.id) if previous_assignee else None,
                    'auto_assigned': user_id is None
                }
            )
            
            # Publish event
            event_publisher.publish(
                'lead.assigned',
                {
                    'lead_id': lead_id,
                    'assigned_to_id': user_id,
                    'assigned_to_name': user.get_full_name() or user.username,
                    'auto_assigned': user_id is None
                }
            )
            
            # Send notification to assignee
            from platform_core.notifications import notification_service
            notification_service.send_notification(
                user_id=user_id,
                title='New Lead Assignment',
                message=f'You have been assigned lead: {lead.company_name}',
                type='lead_assignment',
                data={'lead_id': lead_id}
            )
            
            return {
                'lead_id': lead_id,
                'assigned_to': {
                    'id': user_id,
                    'name': user.get_full_name() or user.username,
                    'email': user.email
                },
                'assigned_date': timezone.now().isoformat(),
                'auto_assigned': user_id is None
            }
            
        except Exception as e:
            logger.error(f"Error assigning lead {lead_id}: {e}")
            raise
    
    def _auto_assign_user(self, lead):
        """Auto-assign lead based on workload and expertise."""
        from django.contrib.auth import get_user_model
        from django.db.models import Count
        
        User = get_user_model()
        
        # Get users with lead management permission
        eligible_users = User.objects.filter(
            is_active=True,
            groups__permissions__codename='manage_leads'
        ).annotate(
            lead_count=Count('assigned_leads', filter=Q(
                assigned_leads__status__in=['new', 'qualified', 'contacted']
            ))
        ).order_by('lead_count')
        
        # Filter by sector expertise if available
        if lead.sector and eligible_users.exists():
            sector_experts = eligible_users.filter(
                profile__expertise_sectors__contains=[lead.sector]
            )
            if sector_experts.exists():
                eligible_users = sector_experts
        
        # Return user with least active leads
        return eligible_users.first()
    
    @cache_result(timeout=600, key_prefix='pipeline_analytics')
    def get_pipeline_analytics(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get lead pipeline analytics.
        
        Cached for 10 minutes.
        """
        from business_modules.investment.models import Lead, LeadActivity
        from django.db.models import Count, Avg, Q, F
        from django.db.models.functions import TruncDate
        
        # Base query
        query = Lead.objects.all()
        
        # Apply filters
        if filters:
            if filters.get('date_from'):
                query = query.filter(created_date__gte=filters['date_from'])
            if filters.get('date_to'):
                query = query.filter(created_date__lte=filters['date_to'])
            if filters.get('sector'):
                query = query.filter(sector=filters['sector'])
            if filters.get('assigned_to_id'):
                query = query.filter(assigned_to_id=filters['assigned_to_id'])
        
        # Calculate metrics
        total_leads = query.count()
        
        # Status breakdown
        status_breakdown = dict(
            query.values('status').annotate(
                count=Count('id')
            ).values_list('status', 'count')
        )
        
        # Conversion funnel
        funnel = {
            'total': total_leads,
            'qualified': query.filter(
                status__in=['qualified', 'contacted', 'negotiating', 'converted']
            ).count(),
            'contacted': query.filter(
                status__in=['contacted', 'negotiating', 'converted']
            ).count(),
            'negotiating': query.filter(
                status__in=['negotiating', 'converted']
            ).count(),
            'converted': query.filter(status='converted').count()
        }
        
        # Calculate conversion rates
        if funnel['total'] > 0:
            funnel['qualification_rate'] = (funnel['qualified'] / funnel['total']) * 100
            funnel['contact_rate'] = (funnel['contacted'] / funnel['qualified']) * 100 if funnel['qualified'] > 0 else 0
            funnel['negotiation_rate'] = (funnel['negotiating'] / funnel['contacted']) * 100 if funnel['contacted'] > 0 else 0
            funnel['conversion_rate'] = (funnel['converted'] / funnel['total']) * 100
        
        # Average scores
        score_metrics = query.aggregate(
            avg_score=Avg('score'),
            avg_qualified_score=Avg('score', filter=Q(status='qualified')),
            avg_converted_score=Avg('score', filter=Q(status='converted'))
        )
        
        # Time metrics
        time_to_qualify = query.filter(
            qualified_date__isnull=False
        ).annotate(
            days_to_qualify=F('qualified_date') - F('created_date')
        ).aggregate(
            avg_days=Avg('days_to_qualify')
        )
        
        # Activity metrics
        recent_activities = LeadActivity.objects.filter(
            lead__in=query,
            created_date__gte=timezone.now() - timedelta(days=30)
        ).count()
        
        # Trend data
        trend = list(
            query.filter(
                created_date__gte=timezone.now() - timedelta(days=30)
            ).annotate(
                date=TruncDate('created_date')
            ).values('date').annotate(
                count=Count('id')
            ).order_by('date')
        )
        
        # Top performers (by conversion)
        top_performers = list(
            User.objects.filter(
                assigned_leads__in=query
            ).annotate(
                total_leads=Count('assigned_leads'),
                converted_leads=Count(
                    'assigned_leads',
                    filter=Q(assigned_leads__status='converted')
                )
            ).filter(
                total_leads__gt=0
            ).annotate(
                conversion_rate=F('converted_leads') * 100.0 / F('total_leads')
            ).order_by('-conversion_rate')[:5].values(
                'id', 'username', 'total_leads', 'converted_leads', 'conversion_rate'
            )
        )
        
        analytics = {
            'summary': {
                'total_leads': total_leads,
                'active_leads': query.filter(
                    status__in=['new', 'qualified', 'contacted', 'negotiating']
                ).count(),
                'converted_leads': funnel['converted'],
                'average_score': score_metrics['avg_score'] or 0
            },
            'funnel': funnel,
            'status_breakdown': status_breakdown,
            'score_metrics': score_metrics,
            'time_metrics': {
                'avg_days_to_qualify': time_to_qualify['avg_days'].days if time_to_qualify['avg_days'] else None
            },
            'activity_metrics': {
                'recent_activities': recent_activities,
                'avg_activities_per_lead': recent_activities / total_leads if total_leads > 0 else 0
            },
            'trend': trend,
            'top_performers': top_performers,
            'generated_at': timezone.now().isoformat()
        }
        
        return analytics
    
    def process_overdue_leads(self) -> List[Dict[str, Any]]:
        """
        Process and flag overdue leads.
        
        Sends notifications and updates status.
        """
        from business_modules.investment.models import Lead, LeadActivity
        
        processed = []
        
        # Define overdue criteria
        overdue_days = {
            'new': 3,
            'qualified': 7,
            'contacted': 14,
            'negotiating': 30
        }
        
        for status, days in overdue_days.items():
            cutoff_date = timezone.now() - timedelta(days=days)
            
            overdue_leads = Lead.objects.filter(
                status=status,
                updated_date__lt=cutoff_date
            )
            
            for lead in overdue_leads:
                try:
                    # Create overdue activity
                    LeadActivity.objects.create(
                        lead=lead,
                        activity_type='flagged_overdue',
                        description=f'Lead overdue in {status} status for {days} days',
                        metadata={
                            'status': status,
                            'days_overdue': days,
                            'last_updated': lead.updated_date.isoformat()
                        }
                    )
                    
                    # Update lead
                    lead.metadata['overdue'] = True
                    lead.metadata['overdue_date'] = timezone.now().isoformat()
                    lead.save()
                    
                    # Send notification to assignee
                    if lead.assigned_to:
                        from platform_core.notifications import notification_service
                        notification_service.send_notification(
                            user_id=str(lead.assigned_to.id),
                            title='Overdue Lead Alert',
                            message=f'Lead {lead.company_name} is overdue for action',
                            type='lead_overdue',
                            priority='high',
                            data={
                                'lead_id': str(lead.id),
                                'status': status,
                                'days_overdue': days
                            }
                        )
                    
                    processed.append({
                        'lead_id': str(lead.id),
                        'company_name': lead.company_name,
                        'status': status,
                        'days_overdue': days,
                        'assigned_to_id': str(lead.assigned_to.id) if lead.assigned_to else None
                    })
                    
                    # Publish event
                    event_publisher.publish(
                        'lead.overdue',
                        {
                            'lead_id': str(lead.id),
                            'status': status,
                            'days_overdue': days
                        }
                    )
                    
                except Exception as e:
                    logger.error(f"Error processing overdue lead {lead.id}: {e}")
        
        logger.info(f"Processed {len(processed)} overdue leads")
        
        # Update real-time metrics
        cache_manager.set(
            'leads:overdue_count',
            len(processed),
            timeout=3600
        )
        
        return processed