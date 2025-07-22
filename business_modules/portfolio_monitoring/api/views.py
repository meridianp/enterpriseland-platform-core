"""
Portfolio Monitoring API Views

ViewSets for portfolio monitoring REST API endpoints.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Sum, Avg, Count
from django.utils import timezone
from datetime import datetime, timedelta
from platform_core.api.views import BaseViewSet
from platform_core.api.permissions import ModulePermission
from ..models import (
    Portfolio, PortfolioHolding, PortfolioPerformance,
    AlertRule, GeneratedReport
)
from ..services import (
    PortfolioAnalyticsService,
    PerformanceCalculationService,
    ReportGenerationService,
    AlertService
)
from .serializers import (
    PortfolioSerializer,
    PortfolioDetailSerializer,
    PortfolioHoldingSerializer,
    PortfolioPerformanceSerializer,
    PortfolioAnalyticsSerializer,
    PortfolioReportSerializer,
    AlertRuleSerializer,
    BulkPerformanceCalculationSerializer
)


class PortfolioViewSet(BaseViewSet):
    """
    ViewSet for portfolio CRUD operations and portfolio-level actions.
    """
    queryset = Portfolio.objects.all()
    serializer_class = PortfolioSerializer
    permission_classes = [IsAuthenticated, ModulePermission]
    filterset_fields = ['status', 'portfolio_type', 'fund_manager']
    search_fields = ['name', 'code', 'management_company']
    ordering_fields = ['inception_date', 'committed_capital', 'name']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'retrieve':
            return PortfolioDetailSerializer
        return super().get_serializer_class()
    
    def get_queryset(self):
        """Apply group filtering and prefetch related data."""
        queryset = super().get_queryset()
        
        # Prefetch related data for performance
        queryset = queryset.select_related('fund_manager')
        
        if self.action == 'retrieve':
            queryset = queryset.prefetch_related(
                'holdings__investment',
                'valuations',
                'performance_records'
            )
        
        # Add annotations for list view
        if self.action == 'list':
            queryset = queryset.annotate(
                holdings_count=Count('holdings'),
                active_holdings_count=Count(
                    'holdings',
                    filter=Q(holdings__status='ACTIVE')
                )
            )
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def performance(self, request, pk=None):
        """
        Get portfolio performance metrics for various periods.
        
        Query params:
        - periods: comma-separated list of periods (MTD,QTD,YTD,1Y,3Y,5Y,ITD)
        - as_of_date: calculation date (default: today)
        - include_holdings: include holding-level performance (default: false)
        """
        portfolio = self.get_object()
        
        # Parse parameters
        periods = request.query_params.get('periods', 'YTD,1Y,3Y,5Y,ITD').split(',')
        as_of_date = request.query_params.get('as_of_date', timezone.now().date())
        include_holdings = request.query_params.get('include_holdings', 'false').lower() == 'true'
        
        # Get performance records
        performance_data = PerformanceCalculationService().calculate_performance(
            portfolio=portfolio,
            periods=periods,
            as_of_date=as_of_date,
            include_holdings=include_holdings
        )
        
        return Response(performance_data)
    
    @action(detail=True, methods=['get'])
    def holdings(self, request, pk=None):
        """Get portfolio holdings with optional filtering."""
        portfolio = self.get_object()
        holdings = portfolio.holdings.select_related('investment')
        
        # Apply filters
        status_filter = request.query_params.get('status')
        if status_filter:
            holdings = holdings.filter(status=status_filter)
        
        holding_type = request.query_params.get('holding_type')
        if holding_type:
            holdings = holdings.filter(holding_type=holding_type)
        
        # Serialize and return
        serializer = PortfolioHoldingSerializer(holdings, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def calculate_performance(self, request, pk=None):
        """
        Manually trigger performance calculation for specific periods.
        """
        portfolio = self.get_object()
        serializer = BulkPerformanceCalculationSerializer(data=request.data)
        
        if serializer.is_valid():
            # Run performance calculation
            service = PerformanceCalculationService()
            results = service.calculate_and_store_performance(
                portfolio=portfolio,
                **serializer.validated_data
            )
            
            return Response({
                'status': 'success',
                'calculations_created': len(results),
                'results': PortfolioPerformanceSerializer(results, many=True).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        """
        Get advanced analytics for the portfolio.
        
        Query params:
        - metrics: comma-separated list of metrics to calculate
        - start_date: analysis start date
        - end_date: analysis end date
        - benchmarks: comma-separated list of benchmark codes
        """
        portfolio = self.get_object()
        
        # Parse parameters
        metrics = request.query_params.get('metrics', '').split(',') if request.query_params.get('metrics') else None
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        benchmarks = request.query_params.get('benchmarks', '').split(',') if request.query_params.get('benchmarks') else []
        
        # Run analytics
        analytics_service = PortfolioAnalyticsService()
        analytics_data = analytics_service.generate_analytics(
            portfolio=portfolio,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            benchmarks=benchmarks
        )
        
        return Response(analytics_data)
    
    @action(detail=True, methods=['post'])
    def generate_report(self, request, pk=None):
        """
        Generate a portfolio report.
        
        Request body:
        - report_type: Type of report (ilpa_quarterly, gips_compliance, etc.)
        - period_start: Report start date
        - period_end: Report end date
        - format: Output format (pdf, excel)
        - parameters: Additional report parameters
        """
        portfolio = self.get_object()
        
        # Validate request data
        report_type = request.data.get('report_type')
        if not report_type:
            return Response(
                {'error': 'report_type is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate report
        report_service = ReportGenerationService()
        report = report_service.generate_report(
            portfolio=portfolio,
            report_type=report_type,
            period_start=request.data.get('period_start'),
            period_end=request.data.get('period_end'),
            format=request.data.get('format', 'pdf'),
            parameters=request.data.get('parameters', {}),
            user=request.user
        )
        
        # Return report details
        serializer = PortfolioReportSerializer(report)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PortfolioHoldingViewSet(BaseViewSet):
    """
    ViewSet for portfolio holdings management.
    """
    queryset = PortfolioHolding.objects.all()
    serializer_class = PortfolioHoldingSerializer
    permission_classes = [IsAuthenticated, ModulePermission]
    filterset_fields = ['portfolio', 'investment', 'status', 'holding_type']
    ordering_fields = ['initial_investment_date', 'current_value', 'gross_irr']
    
    def get_queryset(self):
        """Apply group filtering and optimize queries."""
        queryset = super().get_queryset()
        return queryset.select_related('portfolio', 'investment')
    
    @action(detail=False, methods=['post'])
    def bulk_update_valuations(self, request):
        """
        Bulk update current values for multiple holdings.
        
        Request body:
        - valuations: List of {holding_id, current_value, valuation_date}
        """
        valuations = request.data.get('valuations', [])
        if not valuations:
            return Response(
                {'error': 'valuations list is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        updated_count = 0
        errors = []
        
        for valuation_data in valuations:
            try:
                holding = PortfolioHolding.objects.get(
                    id=valuation_data['holding_id'],
                    portfolio__group=request.user.group
                )
                holding.current_value = valuation_data['current_value']
                holding.save()
                updated_count += 1
            except PortfolioHolding.DoesNotExist:
                errors.append(f"Holding {valuation_data['holding_id']} not found")
            except Exception as e:
                errors.append(f"Error updating {valuation_data['holding_id']}: {str(e)}")
        
        return Response({
            'updated_count': updated_count,
            'errors': errors
        })


class PortfolioPerformanceViewSet(BaseViewSet):
    """
    ViewSet for portfolio performance records.
    """
    queryset = PortfolioPerformance.objects.all()
    serializer_class = PortfolioPerformanceSerializer
    permission_classes = [IsAuthenticated, ModulePermission]
    filterset_fields = ['portfolio', 'period_type', 'is_official']
    ordering_fields = ['period_end', 'calculation_date']
    
    def get_queryset(self):
        """Apply group filtering through portfolio relationship."""
        queryset = super().get_queryset()
        # Filter by user's group through portfolio
        return queryset.filter(
            portfolio__group=self.request.user.group
        ).select_related('portfolio')
    
    @action(detail=False, methods=['post'])
    def calculate_bulk(self, request):
        """
        Calculate performance for multiple portfolios.
        """
        serializer = BulkPerformanceCalculationSerializer(data=request.data)
        
        if serializer.is_valid():
            # Verify access to portfolios
            portfolio_ids = serializer.validated_data['portfolio_ids']
            portfolios = Portfolio.objects.filter(
                id__in=portfolio_ids,
                group=request.user.group
            )
            
            if portfolios.count() != len(portfolio_ids):
                return Response(
                    {'error': 'Some portfolios not found or access denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Run calculations
            service = PerformanceCalculationService()
            results = []
            
            for portfolio in portfolios:
                portfolio_results = service.calculate_and_store_performance(
                    portfolio=portfolio,
                    **serializer.validated_data
                )
                results.extend(portfolio_results)
            
            return Response({
                'status': 'success',
                'calculations_created': len(results),
                'results': PortfolioPerformanceSerializer(results, many=True).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PortfolioAnalyticsViewSet(viewsets.GenericViewSet):
    """
    ViewSet for portfolio analytics operations.
    """
    permission_classes = [IsAuthenticated, ModulePermission]
    serializer_class = PortfolioAnalyticsSerializer
    
    @action(detail=False, methods=['post'])
    def calculate(self, request):
        """
        Calculate advanced analytics for one or more portfolios.
        """
        serializer = self.get_serializer(data=request.data)
        
        if serializer.is_valid():
            # Get portfolios
            portfolio_ids = serializer.validated_data.get('portfolio_ids', [])
            if portfolio_ids:
                portfolios = Portfolio.objects.filter(
                    id__in=portfolio_ids,
                    group=request.user.group
                )
            else:
                portfolios = Portfolio.objects.filter(
                    group=request.user.group,
                    status='ACTIVE'
                )
            
            # Run analytics
            service = PortfolioAnalyticsService()
            analytics_data = service.generate_multi_portfolio_analytics(
                portfolios=portfolios,
                **serializer.validated_data
            )
            
            return Response(analytics_data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def risk_metrics(self, request):
        """
        Get risk metrics across all portfolios.
        """
        portfolios = Portfolio.objects.filter(
            group=request.user.group,
            status='ACTIVE'
        )
        
        service = PortfolioAnalyticsService()
        risk_data = service.calculate_aggregate_risk_metrics(portfolios)
        
        return Response(risk_data)
    
    @action(detail=False, methods=['get'])
    def sector_exposure(self, request):
        """
        Get aggregate sector exposure across portfolios.
        """
        portfolios = Portfolio.objects.filter(
            group=request.user.group,
            status='ACTIVE'
        )
        
        service = PortfolioAnalyticsService()
        exposure_data = service.calculate_sector_exposure(portfolios)
        
        return Response(exposure_data)


class PortfolioReportViewSet(BaseViewSet):
    """
    ViewSet for portfolio reports.
    """
    queryset = GeneratedReport.objects.all()
    serializer_class = PortfolioReportSerializer
    permission_classes = [IsAuthenticated, ModulePermission]
    filterset_fields = ['portfolio', 'report_type', 'status']
    ordering_fields = ['generation_date', 'created_at']
    
    def get_queryset(self):
        """Apply group filtering through portfolio relationship."""
        queryset = super().get_queryset()
        return queryset.filter(
            portfolio__group=self.request.user.group
        ).select_related('portfolio', 'generated_by')
    
    @action(detail=False, methods=['get'])
    def templates(self, request):
        """
        Get available report templates.
        """
        service = ReportGenerationService()
        templates = service.get_available_templates()
        
        return Response(templates)
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """
        Get download URL for a report.
        """
        report = self.get_object()
        
        if report.status != 'COMPLETED':
            return Response(
                {'error': 'Report is not ready for download'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate pre-signed URL for download
        download_url = report.get_download_url()
        
        return Response({
            'download_url': download_url,
            'expires_in': 3600  # URL expires in 1 hour
        })


class PortfolioAlertViewSet(BaseViewSet):
    """
    ViewSet for portfolio alerts configuration.
    """
    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer
    permission_classes = [IsAuthenticated, ModulePermission]
    filterset_fields = ['portfolio', 'rule_type', 'is_active']
    
    def get_queryset(self):
        """Apply group filtering through portfolio relationship."""
        queryset = super().get_queryset()
        return queryset.filter(
            portfolio__group=self.request.user.group
        ).select_related('portfolio')
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """
        Test an alert rule to see if it would trigger.
        """
        alert_rule = self.get_object()
        
        service = AlertService()
        would_trigger, details = service.test_alert_rule(alert_rule)
        
        return Response({
            'would_trigger': would_trigger,
            'current_value': details.get('current_value'),
            'threshold_value': alert_rule.threshold_value,
            'details': details
        })
    
    @action(detail=False, methods=['get'])
    def triggered(self, request):
        """
        Get recently triggered alerts.
        """
        days = int(request.query_params.get('days', 7))
        since_date = timezone.now() - timedelta(days=days)
        
        triggered_alerts = AlertRule.objects.filter(
            portfolio__group=request.user.group,
            last_triggered__gte=since_date
        ).select_related('portfolio').order_by('-last_triggered')
        
        serializer = self.get_serializer(triggered_alerts, many=True)
        return Response(serializer.data)