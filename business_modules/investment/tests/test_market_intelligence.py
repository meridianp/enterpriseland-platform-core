"""
Market Intelligence Service Tests

Tests for news discovery, target identification, and scoring.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.test import TestCase, TransactionTestCase

from business_modules.investment.services import MarketIntelligenceServiceImpl
from business_modules.investment.models import TargetCompany, NewsArticle


class TestMarketIntelligenceService(TestCase):
    """Test market intelligence service functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.service = MarketIntelligenceServiceImpl()
        
        # Mock external dependencies
        self.mock_api_gateway = Mock()
        self.mock_event_publisher = Mock()
        self.mock_cache_manager = Mock()
        
        # Patch dependencies
        self.patches = [
            patch('business_modules.investment.services.market_intelligence.ServiceRegistry', return_value=self.mock_api_gateway),
            patch('business_modules.investment.services.market_intelligence.event_publisher', self.mock_event_publisher),
            patch('business_modules.investment.services.market_intelligence.cache_manager', self.mock_cache_manager),
        ]
        
        for p in self.patches:
            p.start()
    
    def tearDown(self):
        """Clean up patches."""
        for p in self.patches:
            p.stop()
    
    def test_discover_news_success(self):
        """Test successful news discovery."""
        # Mock news service response
        mock_news_data = [
            {
                'title': 'Tech Startup Raises $10M',
                'url': 'https://news.example.com/article1',
                'published_date': '2024-01-15',
                'content': 'A promising tech startup...',
                'source': 'TechNews'
            },
            {
                'title': 'Healthcare Innovation Award',
                'url': 'https://news.example.com/article2',
                'published_date': '2024-01-14',
                'content': 'Leading healthcare company...',
                'source': 'HealthTech'
            }
        ]
        
        # Configure mock
        mock_news_service = Mock()
        mock_news_service.search_news.return_value = mock_news_data
        self.mock_api_gateway.get_service.return_value = mock_news_service
        
        # Execute
        articles = self.service.discover_news()
        
        # Verify
        assert len(articles) == 2
        assert articles[0]['title'] == 'Tech Startup Raises $10M'
        
        # Check event published
        self.mock_event_publisher.publish.assert_called_once()
        event_name, event_data = self.mock_event_publisher.publish.call_args[0]
        assert event_name == 'market_intel.news_discovered'
        assert event_data['discovered_count'] == 2
    
    def test_discover_news_with_query_templates(self):
        """Test news discovery with specific query templates."""
        # Create query templates
        from business_modules.investment.models import QueryTemplate
        
        template1 = QueryTemplate.objects.create(
            name='Tech Investments',
            query_string='technology startup funding',
            is_active=True,
            parameters={'sector': 'technology', 'min_amount': 1000000}
        )
        
        template2 = QueryTemplate.objects.create(
            name='Healthcare Deals',
            query_string='healthcare acquisition merger',
            is_active=True,
            parameters={'sector': 'healthcare'}
        )
        
        # Mock response
        mock_news_service = Mock()
        mock_news_service.search_news.return_value = []
        self.mock_api_gateway.get_service.return_value = mock_news_service
        
        # Execute with template names
        self.service.discover_news(query_templates=['Tech Investments'])
        
        # Verify correct query used
        mock_news_service.search_news.assert_called_once()
        call_args = mock_news_service.search_news.call_args[1]
        assert call_args['query'] == 'technology startup funding'
        assert call_args['params']['sector'] == 'technology'
    
    def test_identify_targets_from_articles(self):
        """Test target company identification from news articles."""
        # Create test articles
        articles = [
            {
                'title': 'Acme Corp Raises $50M Series B',
                'content': 'Acme Corp, a leading fintech startup, announced $50M funding...',
                'url': 'https://example.com/1',
                'metadata': {
                    'companies_mentioned': ['Acme Corp'],
                    'funding_amount': '50000000',
                    'funding_round': 'Series B'
                }
            },
            {
                'title': 'TechCo Acquires DataStart',
                'content': 'TechCo announced acquisition of DataStart for undisclosed sum...',
                'url': 'https://example.com/2',
                'metadata': {
                    'companies_mentioned': ['TechCo', 'DataStart'],
                    'deal_type': 'acquisition'
                }
            }
        ]
        
        # Mock AI service
        mock_ai_service = Mock()
        mock_ai_service.extract_companies.side_effect = [
            {'Acme Corp': {'sector': 'fintech', 'description': 'Payment processing'}},
            {'TechCo': {'sector': 'technology'}, 'DataStart': {'sector': 'data'}}
        ]
        self.mock_api_gateway.get_service.return_value = mock_ai_service
        
        # Execute
        targets = self.service.identify_targets(articles)
        
        # Verify
        assert len(targets) == 3  # Acme Corp, TechCo, DataStart
        assert any(t['name'] == 'Acme Corp' for t in targets)
        assert any(t['sector'] == 'fintech' for t in targets)
        
        # Check database
        assert TargetCompany.objects.count() == 3
        acme = TargetCompany.objects.get(name='Acme Corp')
        assert acme.sector == 'fintech'
    
    def test_score_target_comprehensive(self):
        """Test comprehensive target scoring."""
        # Create target with history
        target = TargetCompany.objects.create(
            name='TestCo',
            sector='technology',
            description='Innovative tech company',
            metadata={
                'employees': 150,
                'revenue': '25000000',
                'growth_rate': '45',
                'market_presence': 'high'
            }
        )
        
        # Create news articles
        for i in range(5):
            NewsArticle.objects.create(
                title=f'TestCo News {i}',
                url=f'https://example.com/{i}',
                content=f'Positive news about TestCo {i}',
                published_date=timezone.now() - timedelta(days=i)
            )
        
        # Execute scoring
        score = self.service.score_target({'id': str(target.id)})
        
        # Verify
        assert isinstance(score, float)
        assert 0 <= score <= 100
        
        # Check components
        target.refresh_from_db()
        assert 'business_alignment' in target.score_components
        assert 'market_presence' in target.score_components
        assert 'financial_strength' in target.score_components
        assert 'strategic_fit' in target.score_components
    
    def test_get_market_trends(self):
        """Test market trends analysis."""
        # Create historical data
        base_date = timezone.now()
        sectors = ['technology', 'healthcare', 'fintech']
        
        for i in range(30):
            date = base_date - timedelta(days=i)
            for sector in sectors:
                # Create targets
                for j in range(3):
                    TargetCompany.objects.create(
                        name=f'{sector}_company_{i}_{j}',
                        sector=sector,
                        discovered_date=date,
                        score=70 + (i % 20)  # Varying scores
                    )
        
        # Execute trends analysis
        trends = self.service.get_market_trends(period='month')
        
        # Verify
        assert 'sectors' in trends
        assert 'time_series' in trends
        assert 'top_sectors' in trends
        assert 'discovery_rate' in trends
        
        # Check sector data
        assert len(trends['sectors']) == 3
        tech_data = next(s for s in trends['sectors'] if s['sector'] == 'technology')
        assert tech_data['company_count'] > 0
        assert 'average_score' in tech_data
    
    def test_track_competitor(self):
        """Test competitor tracking functionality."""
        # Create competitor
        competitor = TargetCompany.objects.create(
            name='CompetitorCo',
            sector='technology',
            is_competitor=True,
            metadata={
                'market_cap': '500000000',
                'employees': 1000
            }
        )
        
        # Create competitor activities
        activities = [
            {'type': 'funding', 'amount': '25000000', 'date': '2024-01-10'},
            {'type': 'acquisition', 'target': 'SmallCo', 'date': '2024-01-05'},
            {'type': 'product_launch', 'product': 'New Platform', 'date': '2024-01-01'}
        ]
        
        # Mock external data
        mock_intel_service = Mock()
        mock_intel_service.get_company_updates.return_value = activities
        self.mock_api_gateway.get_service.return_value = mock_intel_service
        
        # Execute
        tracking_data = self.service.track_competitor(str(competitor.id))
        
        # Verify
        assert tracking_data['competitor_id'] == str(competitor.id)
        assert tracking_data['competitor_name'] == 'CompetitorCo'
        assert len(tracking_data['recent_activities']) == 3
        assert tracking_data['threat_level'] in ['low', 'medium', 'high']
    
    @patch('business_modules.investment.services.market_intelligence.cache_result')
    def test_caching_behavior(self, mock_cache_decorator):
        """Test that caching is properly configured."""
        # Ensure cache decorator is applied
        mock_cache_decorator.return_value = lambda f: f
        
        # Re-import to apply decorator
        from business_modules.investment.services.market_intelligence import MarketIntelligenceServiceImpl
        
        # Verify decorator was called with correct params
        mock_cache_decorator.assert_called()
        call_args = mock_cache_decorator.call_args_list
        
        # Check that discover_news has 1 hour cache
        news_cache_call = next(
            c for c in call_args 
            if c[1].get('key_prefix') == 'market_intel'
        )
        assert news_cache_call[1]['timeout'] == 3600
    
    def test_real_time_analytics_update(self):
        """Test real-time analytics updates."""
        # Create initial targets
        for i in range(5):
            TargetCompany.objects.create(
                name=f'Target{i}',
                sector='technology',
                score=70 + i * 5
            )
        
        # Mock real-time structures
        mock_counter = Mock()
        mock_counter.get.return_value = 10
        self.service.target_counter = mock_counter
        
        mock_scores = Mock()
        self.service.target_scores = mock_scores
        
        # Discover news (triggers counter update)
        mock_news_service = Mock()
        mock_news_service.search_news.return_value = []
        self.mock_api_gateway.get_service.return_value = mock_news_service
        
        self.service.discover_news()
        
        # Verify counter incremented
        mock_counter.increment.assert_called_with(window='hour')
        
        # Score a target (triggers leaderboard update)
        target = TargetCompany.objects.first()
        score = self.service.score_target({'id': str(target.id)})
        
        # Verify leaderboard updated
        mock_scores.add_score.assert_called_with(
            f'target:{target.id}',
            score
        )
    
    def test_error_handling_external_service(self):
        """Test graceful handling of external service failures."""
        # Mock service failure
        mock_news_service = Mock()
        mock_news_service.search_news.side_effect = Exception('Service unavailable')
        self.mock_api_gateway.get_service.return_value = mock_news_service
        
        # Execute - should not raise
        articles = self.service.discover_news()
        
        # Verify empty result returned
        assert articles == []
        
        # Check that error was logged (would need to mock logger)
    
    def test_sector_filtering(self):
        """Test sector-based filtering in trends."""
        # Create sector-specific data
        TargetCompany.objects.create(
            name='TechCo1',
            sector='technology',
            score=85
        )
        
        TargetCompany.objects.create(
            name='HealthCo1',
            sector='healthcare',
            score=75
        )
        
        # Get technology trends only
        tech_trends = self.service.get_market_trends(
            sector='technology',
            period='month'
        )
        
        # Verify only tech data returned
        assert len(tech_trends['sectors']) == 1
        assert tech_trends['sectors'][0]['sector'] == 'technology'


class TestMarketIntelligenceIntegration(TransactionTestCase):
    """Integration tests for market intelligence with platform services."""
    
    def setUp(self):
        """Set up integration test environment."""
        self.service = MarketIntelligenceServiceImpl()
    
    @patch('business_modules.investment.services.market_intelligence.websocket_manager')
    @patch('business_modules.investment.services.market_intelligence.event_publisher')
    def test_websocket_notification_flow(self, mock_events, mock_ws):
        """Test WebSocket notifications are sent correctly."""
        # Create target
        target = TargetCompany.objects.create(
            name='NotifyTestCo',
            sector='technology'
        )
        
        # Score target (triggers notifications)
        self.service.score_target({'id': str(target.id)})
        
        # Verify WebSocket notification sent
        mock_ws.send_to_channel.assert_called()
        channel, data = mock_ws.send_to_channel.call_args[0]
        assert channel == 'market-intel'
        assert data['type'] == 'target.scored'
        assert data['data']['target_id'] == str(target.id)
    
    def test_concurrent_target_identification(self):
        """Test thread-safe target identification."""
        from concurrent.futures import ThreadPoolExecutor
        import threading
        
        # Track created targets
        created_targets = []
        lock = threading.Lock()
        
        def identify_targets_thread(articles):
            targets = self.service.identify_targets(articles)
            with lock:
                created_targets.extend(targets)
        
        # Create test articles
        articles = [
            {
                'title': f'Company{i} News',
                'content': f'Company{i} announces growth',
                'url': f'https://example.com/{i}'
            }
            for i in range(10)
        ]
        
        # Mock AI service
        with patch('business_modules.investment.services.market_intelligence.ServiceRegistry') as mock_registry:
            mock_ai = Mock()
            mock_ai.extract_companies.return_value = {
                f'Company{i}': {'sector': 'tech'} 
                for i in range(10)
            }
            mock_registry.return_value.get_service.return_value = mock_ai
            
            # Execute concurrent identification
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = []
                for i in range(5):
                    future = executor.submit(
                        identify_targets_thread,
                        articles[i*2:(i+1)*2]
                    )
                    futures.append(future)
                
                # Wait for completion
                for future in futures:
                    future.result()
        
        # Verify no duplicates created
        company_names = [t['name'] for t in created_targets]
        assert len(company_names) == len(set(company_names))