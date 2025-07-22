"""
Portfolio Monitoring API URL Configuration
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PortfolioViewSet,
    PortfolioHoldingViewSet,
    PortfolioPerformanceViewSet,
    PortfolioAnalyticsViewSet,
    PortfolioReportViewSet,
    PortfolioAlertViewSet
)

# Create router
router = DefaultRouter()

# Register viewsets
router.register(r'portfolios', PortfolioViewSet, basename='portfolio')
router.register(r'holdings', PortfolioHoldingViewSet, basename='portfolio-holding')
router.register(r'performance', PortfolioPerformanceViewSet, basename='portfolio-performance')
router.register(r'analytics', PortfolioAnalyticsViewSet, basename='portfolio-analytics')
router.register(r'reports', PortfolioReportViewSet, basename='portfolio-report')
router.register(r'alerts', PortfolioAlertViewSet, basename='portfolio-alert')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]

# Module API info for registration
api_info = {
    'module': 'portfolio_monitoring',
    'version': 'v1',
    'endpoints': [
        {
            'path': 'portfolios/',
            'name': 'Portfolios',
            'description': 'Portfolio CRUD operations and management'
        },
        {
            'path': 'portfolios/{id}/performance/',
            'name': 'Portfolio Performance',
            'description': 'Get portfolio performance metrics'
        },
        {
            'path': 'portfolios/{id}/holdings/',
            'name': 'Portfolio Holdings',
            'description': 'Manage portfolio holdings'
        },
        {
            'path': 'portfolios/{id}/analytics/',
            'name': 'Portfolio Analytics',
            'description': 'Advanced portfolio analytics'
        },
        {
            'path': 'portfolios/{id}/generate_report/',
            'name': 'Generate Report',
            'description': 'Generate portfolio reports'
        },
        {
            'path': 'holdings/',
            'name': 'Holdings',
            'description': 'Portfolio holdings management'
        },
        {
            'path': 'performance/',
            'name': 'Performance Records',
            'description': 'Historical performance records'
        },
        {
            'path': 'analytics/calculate/',
            'name': 'Calculate Analytics',
            'description': 'Calculate multi-portfolio analytics'
        },
        {
            'path': 'reports/',
            'name': 'Reports',
            'description': 'Generated portfolio reports'
        },
        {
            'path': 'alerts/',
            'name': 'Alerts',
            'description': 'Portfolio alert rules'
        }
    ]
}