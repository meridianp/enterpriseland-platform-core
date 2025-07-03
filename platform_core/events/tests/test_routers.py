"""
Tests for Event Routers
"""

from unittest.mock import Mock, patch
from django.test import TestCase

from platform_core.events.routers import (
    RouteRule,
    MatchType,
    EventRouter,
    ContentBasedRouter,
    TopicRouter,
    FanoutRouter,
    CompositeRouter
)
from platform_core.events.brokers import Message


class RouteRuleTestCase(TestCase):
    """Test RouteRule."""
    
    def test_exact_match(self):
        """Test exact event type matching."""
        rule = RouteRule(
            event_types=['user.created', 'user.updated'],
            match_type=MatchType.EXACT,
            target='user-queue'
        )
        
        self.assertTrue(rule.matches('user.created'))
        self.assertTrue(rule.matches('user.updated'))
        self.assertFalse(rule.matches('user.deleted'))
        self.assertFalse(rule.matches('order.created'))
    
    def test_prefix_match(self):
        """Test prefix matching."""
        rule = RouteRule(
            event_types=['user.', 'order.'],
            match_type=MatchType.PREFIX,
            target='events-queue'
        )
        
        self.assertTrue(rule.matches('user.created'))
        self.assertTrue(rule.matches('user.updated'))
        self.assertTrue(rule.matches('order.placed'))
        self.assertFalse(rule.matches('payment.processed'))
    
    def test_pattern_match(self):
        """Test wildcard pattern matching."""
        rule = RouteRule(
            event_types=['*.created', 'user.*', '*.*.error'],
            match_type=MatchType.PATTERN,
            target='pattern-queue'
        )
        
        self.assertTrue(rule.matches('user.created'))
        self.assertTrue(rule.matches('order.created'))
        self.assertTrue(rule.matches('user.updated'))
        self.assertTrue(rule.matches('payment.processing.error'))
        self.assertFalse(rule.matches('order.updated'))
    
    def test_regex_match(self):
        """Test regex matching."""
        rule = RouteRule(
            event_types=[r'^user\.(created|updated)$', r'.*\.error$'],
            match_type=MatchType.REGEX,
            target='regex-queue'
        )
        
        self.assertTrue(rule.matches('user.created'))
        self.assertTrue(rule.matches('user.updated'))
        self.assertTrue(rule.matches('payment.error'))
        self.assertTrue(rule.matches('order.processing.error'))
        self.assertFalse(rule.matches('user.deleted'))
    
    def test_filter_function(self):
        """Test filter function."""
        def high_priority_filter(message):
            return message.data.get('priority') == 'high'
        
        rule = RouteRule(
            event_types=['*'],
            match_type=MatchType.PATTERN,
            target='high-priority-queue',
            filter_func=high_priority_filter
        )
        
        # High priority message
        high_msg = Message(
            id='1',
            event_type='test.event',
            data={'priority': 'high'}
        )
        self.assertTrue(rule.should_route(high_msg))
        
        # Low priority message
        low_msg = Message(
            id='2',
            event_type='test.event',
            data={'priority': 'low'}
        )
        self.assertFalse(rule.should_route(low_msg))
    
    def test_transform_function(self):
        """Test transform function."""
        def add_timestamp(message):
            message.metadata['routed_at'] = 'test-time'
            return message
        
        rule = RouteRule(
            event_types=['*'],
            match_type=MatchType.PATTERN,
            target='transform-queue',
            transform_func=add_timestamp
        )
        
        message = Message(
            id='1',
            event_type='test.event',
            data={},
            metadata={}
        )
        
        transformed = rule.transform_message(message)
        self.assertEqual(transformed.metadata['routed_at'], 'test-time')


class EventRouterTestCase(TestCase):
    """Test EventRouter."""
    
    def setUp(self):
        self.router = EventRouter()
    
    def test_add_rule(self):
        """Test adding routing rules."""
        rule = self.router.add_rule(
            event_types=['user.created'],
            target='user-queue',
            priority=10
        )
        
        self.assertIn(rule, self.router.rules)
        self.assertEqual(len(self.router.rules), 1)
    
    def test_rule_priority_ordering(self):
        """Test rules are ordered by priority."""
        self.router.add_rule(['*'], 'low-queue', priority=1)
        self.router.add_rule(['*'], 'high-queue', priority=100)
        self.router.add_rule(['*'], 'medium-queue', priority=50)
        
        # Check order (highest priority first)
        self.assertEqual(self.router.rules[0].target, 'high-queue')
        self.assertEqual(self.router.rules[1].target, 'medium-queue')
        self.assertEqual(self.router.rules[2].target, 'low-queue')
    
    def test_route_message(self):
        """Test routing a message."""
        self.router.add_rule(
            event_types=['user.*'],
            target='user-queue',
            match_type=MatchType.PATTERN
        )
        self.router.add_rule(
            event_types=['*.created'],
            target='created-queue',
            match_type=MatchType.PATTERN
        )
        
        message = Message(
            id='1',
            event_type='user.created',
            data={}
        )
        
        targets = self.router.route(message)
        
        # Should match both rules
        self.assertIn('user-queue', targets)
        self.assertIn('created-queue', targets)
        self.assertEqual(len(targets), 2)
    
    @patch('platform_core.events.models.EventSubscription.objects.filter')
    def test_default_routing(self, mock_filter):
        """Test default routing when no rules match."""
        # Mock subscriptions
        mock_sub = Mock()
        mock_sub.endpoint = 'default-subscription-queue'
        mock_filter.return_value = [mock_sub]
        
        message = Message(
            id='1',
            event_type='unknown.event',
            data={}
        )
        
        with patch('django.conf.settings.EVENT_DEFAULT_QUEUE', 'default-queue'):
            targets = self.router.route(message)
        
        self.assertIn('default-subscription-queue', targets)
        self.assertIn('default-queue', targets)


class ContentBasedRouterTestCase(TestCase):
    """Test ContentBasedRouter."""
    
    def setUp(self):
        self.router = ContentBasedRouter()
    
    def test_content_rule_equals(self):
        """Test content-based routing with equals operator."""
        self.router.add_content_rule(
            field_path='priority',
            operator='eq',
            value='high',
            target='high-priority-queue'
        )
        
        # High priority message
        message = Message(
            id='1',
            event_type='test.event',
            data={'priority': 'high'}
        )
        
        targets = self.router.route(message)
        self.assertIn('high-priority-queue', targets)
        
        # Low priority message
        message.data['priority'] = 'low'
        targets = self.router.route(message)
        self.assertNotIn('high-priority-queue', targets)
    
    def test_content_rule_comparison(self):
        """Test content-based routing with comparison operators."""
        self.router.add_content_rule(
            field_path='amount',
            operator='gt',
            value=100,
            target='large-amount-queue'
        )
        
        # Large amount
        message = Message(
            id='1',
            event_type='payment.processed',
            data={'amount': 150}
        )
        
        targets = self.router.route(message)
        self.assertIn('large-amount-queue', targets)
        
        # Small amount
        message.data['amount'] = 50
        targets = self.router.route(message)
        self.assertNotIn('large-amount-queue', targets)
    
    def test_content_rule_nested_field(self):
        """Test content-based routing with nested fields."""
        self.router.add_content_rule(
            field_path='user.role',
            operator='eq',
            value='admin',
            target='admin-queue'
        )
        
        message = Message(
            id='1',
            event_type='action.performed',
            data={
                'user': {
                    'id': '123',
                    'role': 'admin'
                }
            }
        )
        
        targets = self.router.route(message)
        self.assertIn('admin-queue', targets)


class TopicRouterTestCase(TestCase):
    """Test TopicRouter."""
    
    def setUp(self):
        self.router = TopicRouter()
    
    def test_topic_binding_single_wildcard(self):
        """Test topic binding with single wildcard (*)."""
        self.router.add_topic_binding('order.*.shipped', 'shipping-queue')
        
        message1 = Message(id='1', event_type='order.123.shipped', data={})
        message2 = Message(id='2', event_type='order.456.shipped', data={})
        message3 = Message(id='3', event_type='order.shipped', data={})
        message4 = Message(id='4', event_type='order.123.456.shipped', data={})
        
        self.assertIn('shipping-queue', self.router.route(message1))
        self.assertIn('shipping-queue', self.router.route(message2))
        self.assertNotIn('shipping-queue', self.router.route(message3))
        self.assertNotIn('shipping-queue', self.router.route(message4))
    
    def test_topic_binding_multi_wildcard(self):
        """Test topic binding with multi wildcard (#)."""
        self.router.add_topic_binding('#.error', 'error-queue')
        
        message1 = Message(id='1', event_type='payment.error', data={})
        message2 = Message(id='2', event_type='order.processing.error', data={})
        message3 = Message(id='3', event_type='error', data={})
        message4 = Message(id='4', event_type='payment.success', data={})
        
        self.assertIn('error-queue', self.router.route(message1))
        self.assertIn('error-queue', self.router.route(message2))
        self.assertIn('error-queue', self.router.route(message3))
        self.assertNotIn('error-queue', self.router.route(message4))


class FanoutRouterTestCase(TestCase):
    """Test FanoutRouter."""
    
    def setUp(self):
        self.router = FanoutRouter()
    
    def test_fanout_group(self):
        """Test fanout to group."""
        self.router.add_to_fanout_group('notifications', 'email-queue')
        self.router.add_to_fanout_group('notifications', 'sms-queue')
        self.router.add_to_fanout_group('notifications', 'push-queue')
        
        message = Message(
            id='1',
            event_type='user.notification',
            data={}
        )
        
        targets = self.router.fanout_to_group(message, 'notifications')
        
        self.assertEqual(len(targets), 3)
        self.assertIn('email-queue', targets)
        self.assertIn('sms-queue', targets)
        self.assertIn('push-queue', targets)
    
    def test_remove_from_fanout_group(self):
        """Test removing from fanout group."""
        self.router.add_to_fanout_group('test', 'queue-1')
        self.router.add_to_fanout_group('test', 'queue-2')
        
        self.router.remove_from_fanout_group('test', 'queue-1')
        
        message = Message(id='1', event_type='test', data={})
        targets = self.router.fanout_to_group(message, 'test')
        
        self.assertEqual(len(targets), 1)
        self.assertIn('queue-2', targets)
        self.assertNotIn('queue-1', targets)


class CompositeRouterTestCase(TestCase):
    """Test CompositeRouter."""
    
    def test_composite_routing(self):
        """Test combining multiple routers."""
        composite = CompositeRouter()
        
        # Basic router
        basic_router = EventRouter()
        basic_router.add_rule(['user.*'], 'user-queue', match_type=MatchType.PATTERN)
        
        # Content router
        content_router = ContentBasedRouter()
        content_router.add_content_rule('priority', 'eq', 'high', 'priority-queue')
        
        # Add to composite
        composite.add_router(basic_router)
        composite.add_router(content_router)
        
        # Route message that matches both
        message = Message(
            id='1',
            event_type='user.created',
            data={'priority': 'high'}
        )
        
        targets = composite.route(message)
        
        self.assertIn('user-queue', targets)
        self.assertIn('priority-queue', targets)
        self.assertEqual(len(targets), 2)