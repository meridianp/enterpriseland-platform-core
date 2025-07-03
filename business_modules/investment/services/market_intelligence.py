"""
Market Intelligence Service Implementation

Leverages platform services for news discovery and analysis.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction

from platform_core.cache import cache_result, cache_manager
from platform_core.events import event_publisher
from platform_core.gateway import ServiceRegistry
from business_modules.investment.interfaces import MarketIntelligenceService

logger = logging.getLogger(__name__)


class MarketIntelligenceServiceImpl(MarketIntelligenceService):
    """
    Implementation of market intelligence service.
    
    Uses platform caching, events, and external service integration.
    """
    
    def __init__(self):
        """Initialize service."""
        self.cache_prefix = "market_intel"
        self._init_external_services()
    
    def _init_external_services(self):
        """Initialize connections to external news services."""
        try:
            # Get news API services from gateway
            self.news_services = ServiceRegistry.objects.filter(
                tags__contains=['news', 'market-data']
            )
        except Exception as e:
            logger.warning(f"Could not load news services: {e}")
            self.news_services = []
    
    @cache_result(timeout=3600, key_prefix='market_intel')
    def discover_news(self, query_templates: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Discover news articles based on query templates.
        
        Caches results for 1 hour to reduce API calls.
        """
        from business_modules.investment.models import QueryTemplate, NewsArticle
        
        # Get query templates
        if query_templates:
            templates = QueryTemplate.objects.filter(name__in=query_templates)
        else:
            templates = QueryTemplate.objects.filter(is_active=True)
        
        discovered_articles = []
        
        for template in templates:
            try:
                # Discover news for this template
                articles = self._discover_for_template(template)
                
                # Save articles to database
                for article_data in articles:
                    article, created = NewsArticle.objects.update_or_create(
                        external_id=article_data['external_id'],
                        defaults={
                            'title': article_data['title'],
                            'content': article_data.get('content', ''),
                            'summary': article_data.get('summary', ''),
                            'source': article_data['source'],
                            'url': article_data['url'],
                            'published_date': article_data['published_date'],
                            'discovered_date': timezone.now(),
                            'query_template': template,
                            'metadata': article_data.get('metadata', {})
                        }
                    )
                    
                    if created:
                        discovered_articles.append(article_data)
                        
                        # Publish event
                        event_publisher.publish(
                            'market_intel.news_discovered',
                            {
                                'article_id': str(article.id),
                                'title': article.title,
                                'source': article.source,
                                'template': template.name
                            }
                        )
                
            except Exception as e:
                logger.error(f"Error discovering news for template {template.name}: {e}")
        
        logger.info(f"Discovered {len(discovered_articles)} new articles")
        return discovered_articles
    
    def _discover_for_template(self, template) -> List[Dict[str, Any]]:
        """Discover news for a specific template."""
        articles = []
        
        # Call external news services
        for service in self.news_services:
            try:
                # Use API Gateway to call service
                from platform_core.gateway import gateway_client
                
                response = gateway_client.call_service(
                    service.name,
                    'search',
                    {
                        'query': template.query_string,
                        'from_date': (timezone.now() - timedelta(days=7)).isoformat(),
                        'limit': 100
                    }
                )
                
                if response.get('articles'):
                    articles.extend(response['articles'])
                    
            except Exception as e:
                logger.error(f"Error calling news service {service.name}: {e}")
        
        return articles
    
    @transaction.atomic
    def identify_targets(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Identify potential target companies from news articles.
        
        Uses AI/ML to extract company information.
        """
        from business_modules.investment.models import TargetCompany, NewsArticle
        
        identified_targets = []
        
        for article_data in articles:
            try:
                # Get article from database
                article = NewsArticle.objects.get(external_id=article_data['external_id'])
                
                # Extract companies using NLP
                companies = self._extract_companies(article)
                
                for company_data in companies:
                    target, created = TargetCompany.objects.update_or_create(
                        name=company_data['name'],
                        defaults={
                            'sector': company_data.get('sector'),
                            'description': company_data.get('description'),
                            'website': company_data.get('website'),
                            'metadata': company_data.get('metadata', {}),
                            'discovered_date': timezone.now()
                        }
                    )
                    
                    # Link to article
                    target.source_articles.add(article)
                    
                    if created:
                        identified_targets.append({
                            'id': str(target.id),
                            'name': target.name,
                            'sector': target.sector,
                            'confidence': company_data.get('confidence', 0.5)
                        })
                        
                        # Publish event
                        event_publisher.publish(
                            'market_intel.target_identified',
                            {
                                'target_id': str(target.id),
                                'name': target.name,
                                'source_article': str(article.id)
                            }
                        )
                
            except Exception as e:
                logger.error(f"Error identifying targets from article: {e}")
        
        return identified_targets
    
    def _extract_companies(self, article) -> List[Dict[str, Any]]:
        """Extract company information from article using NLP."""
        # This would integrate with an NLP service
        # For now, return mock data
        return [
            {
                'name': 'Example Company',
                'sector': 'Technology',
                'description': 'Extracted from article',
                'confidence': 0.85
            }
        ]
    
    @cache_result(timeout=300, tags=['scoring'])
    def score_target(self, target: Dict[str, Any]) -> float:
        """
        Score a target company based on investment criteria.
        
        Cached for 5 minutes with tag-based invalidation.
        """
        from business_modules.investment.models import TargetCompany
        
        try:
            if isinstance(target, dict):
                target_obj = TargetCompany.objects.get(id=target['id'])
            else:
                target_obj = target
            
            # Calculate score components
            scores = {
                'business_alignment': self._score_business_alignment(target_obj),
                'market_presence': self._score_market_presence(target_obj),
                'financial_strength': self._score_financial_strength(target_obj),
                'strategic_fit': self._score_strategic_fit(target_obj)
            }
            
            # Weighted average
            weights = {
                'business_alignment': 0.3,
                'market_presence': 0.2,
                'financial_strength': 0.3,
                'strategic_fit': 0.2
            }
            
            total_score = sum(
                scores[key] * weights[key] 
                for key in scores
            )
            
            # Update target score
            target_obj.score = total_score
            target_obj.score_components = scores
            target_obj.scored_date = timezone.now()
            target_obj.save()
            
            # Publish scoring event
            event_publisher.publish(
                'market_intel.target_scored',
                {
                    'target_id': str(target_obj.id),
                    'score': total_score,
                    'components': scores
                }
            )
            
            return total_score
            
        except Exception as e:
            logger.error(f"Error scoring target: {e}")
            return 0.0
    
    def _score_business_alignment(self, target) -> float:
        """Score business alignment."""
        # Implement scoring logic
        return 75.0
    
    def _score_market_presence(self, target) -> float:
        """Score market presence."""
        # Implement scoring logic
        return 80.0
    
    def _score_financial_strength(self, target) -> float:
        """Score financial strength."""
        # Implement scoring logic
        return 70.0
    
    def _score_strategic_fit(self, target) -> float:
        """Score strategic fit."""
        # Implement scoring logic
        return 85.0
    
    @cache_result(timeout=1800, key_prefix='market_trends')
    def get_market_trends(self, sector: Optional[str] = None, 
                         period: str = 'month') -> Dict[str, Any]:
        """
        Get market trends and analytics.
        
        Cached for 30 minutes.
        """
        from business_modules.investment.models import NewsArticle, TargetCompany
        from django.db.models import Count, Avg, Q
        
        # Calculate date range
        end_date = timezone.now()
        if period == 'day':
            start_date = end_date - timedelta(days=1)
        elif period == 'week':
            start_date = end_date - timedelta(weeks=1)
        elif period == 'month':
            start_date = end_date - timedelta(days=30)
        else:
            start_date = end_date - timedelta(days=365)
        
        # Build queries
        article_query = NewsArticle.objects.filter(
            published_date__gte=start_date
        )
        target_query = TargetCompany.objects.filter(
            discovered_date__gte=start_date
        )
        
        if sector:
            target_query = target_query.filter(sector=sector)
        
        # Calculate trends
        trends = {
            'period': period,
            'sector': sector,
            'metrics': {
                'total_articles': article_query.count(),
                'total_targets': target_query.count(),
                'avg_target_score': target_query.aggregate(
                    avg_score=Avg('score')
                )['avg_score'] or 0,
                'top_sectors': list(
                    target_query.values('sector').annotate(
                        count=Count('id')
                    ).order_by('-count')[:5]
                ),
                'discovery_trend': self._calculate_discovery_trend(
                    start_date, end_date, sector
                )
            }
        }
        
        return trends
    
    def _calculate_discovery_trend(self, start_date, end_date, sector=None):
        """Calculate discovery trend over time."""
        from business_modules.investment.models import TargetCompany
        from django.db.models import Count
        from django.db.models.functions import TruncDate
        
        query = TargetCompany.objects.filter(
            discovered_date__range=[start_date, end_date]
        )
        
        if sector:
            query = query.filter(sector=sector)
        
        trend = list(
            query.annotate(
                date=TruncDate('discovered_date')
            ).values('date').annotate(
                count=Count('id')
            ).order_by('date')
        )
        
        return trend
    
    def track_competitor(self, competitor_id: str) -> Dict[str, Any]:
        """
        Track competitor activities and news.
        
        Uses real-time monitoring.
        """
        from business_modules.investment.models import Competitor
        
        try:
            competitor = Competitor.objects.get(id=competitor_id)
            
            # Get recent news mentions
            recent_news = NewsArticle.objects.filter(
                content__icontains=competitor.name,
                published_date__gte=timezone.now() - timedelta(days=30)
            ).order_by('-published_date')[:10]
            
            # Get competitor deals
            recent_deals = Deal.objects.filter(
                competitors__id=competitor_id,
                created_date__gte=timezone.now() - timedelta(days=90)
            )
            
            tracking_data = {
                'competitor': {
                    'id': str(competitor.id),
                    'name': competitor.name,
                    'sector': competitor.sector
                },
                'recent_news': [
                    {
                        'title': article.title,
                        'date': article.published_date.isoformat(),
                        'source': article.source,
                        'url': article.url
                    }
                    for article in recent_news
                ],
                'deal_activity': {
                    'total': recent_deals.count(),
                    'by_stage': dict(
                        recent_deals.values('current_stage').annotate(
                            count=Count('id')
                        ).values_list('current_stage', 'count')
                    )
                },
                'last_updated': timezone.now().isoformat()
            }
            
            # Cache the tracking data
            cache_manager.set(
                f'competitor_tracking:{competitor_id}',
                tracking_data,
                timeout=300  # 5 minutes
            )
            
            return tracking_data
            
        except Competitor.DoesNotExist:
            logger.error(f"Competitor {competitor_id} not found")
            return {}