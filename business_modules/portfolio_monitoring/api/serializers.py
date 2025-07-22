"""
Portfolio Monitoring API Serializers

Serializers for portfolio monitoring REST API endpoints.
"""
from rest_framework import serializers
from django.db.models import Q, Sum, Avg
from decimal import Decimal
from platform_core.api.serializers import BaseSerializer
from ..models import (
    Portfolio, PortfolioHolding, PortfolioValuation,
    PortfolioPerformance, PerformanceMetric,
    AlertRule, GeneratedReport
)


class PortfolioHoldingSerializer(BaseSerializer):
    """Serializer for portfolio holdings."""
    
    investment_name = serializers.CharField(source='investment.name', read_only=True)
    investment_code = serializers.CharField(source='investment.code', read_only=True)
    unrealized_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    multiple_on_invested_capital = serializers.DecimalField(max_digits=6, decimal_places=3, read_only=True)
    
    class Meta:
        model = PortfolioHolding
        fields = [
            'id', 'portfolio', 'investment', 'investment_name', 'investment_code',
            'holding_type', 'status', 'initial_investment_date', 'exit_date',
            'committed_amount', 'invested_amount', 'current_value',
            'realized_value', 'unrealized_value', 'total_value',
            'total_distributions', 'ownership_percentage',
            'diluted_ownership_percentage', 'gross_multiple', 'gross_irr',
            'net_multiple', 'net_irr', 'multiple_on_invested_capital',
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PortfolioPerformanceSerializer(BaseSerializer):
    """Serializer for portfolio performance records."""
    
    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)
    
    class Meta:
        model = PortfolioPerformance
        fields = [
            'id', 'portfolio', 'portfolio_name', 'period_type',
            'period_start', 'period_end', 'calculation_date',
            'gross_return', 'net_return', 'gross_irr', 'net_irr',
            'gross_multiple', 'net_multiple', 'total_contributions',
            'total_distributions', 'net_cash_flow', 'beginning_value',
            'ending_value', 'average_capital', 'volatility',
            'sharpe_ratio', 'max_drawdown', 'calculation_method',
            'calculation_parameters', 'is_official', 'notes'
        ]
        read_only_fields = ['id', 'calculation_date']


class PortfolioSerializer(BaseSerializer):
    """Basic portfolio serializer."""
    
    fund_manager_name = serializers.CharField(source='fund_manager.get_full_name', read_only=True)
    uncalled_capital = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    net_asset_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_value_to_paid_in = serializers.DecimalField(max_digits=6, decimal_places=3, read_only=True)
    distributions_to_paid_in = serializers.DecimalField(max_digits=6, decimal_places=3, read_only=True)
    residual_value_to_paid_in = serializers.DecimalField(max_digits=6, decimal_places=3, read_only=True)
    holdings_count = serializers.IntegerField(read_only=True)
    active_holdings_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Portfolio
        fields = [
            'id', 'name', 'code', 'portfolio_type', 'status',
            'inception_date', 'termination_date', 'base_currency',
            'target_size', 'committed_capital', 'called_capital',
            'distributed_capital', 'uncalled_capital', 'net_asset_value',
            'investment_strategy', 'target_sectors', 'target_geographies',
            'target_return', 'fund_manager', 'fund_manager_name',
            'management_company', 'management_fee_percentage',
            'carried_interest_percentage', 'total_value_to_paid_in',
            'distributions_to_paid_in', 'residual_value_to_paid_in',
            'holdings_count', 'active_holdings_count', 'tags',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_holdings_count(self, obj):
        return obj.holdings.count()
    
    def get_active_holdings_count(self, obj):
        return obj.holdings.filter(status='ACTIVE').count()


class PortfolioDetailSerializer(PortfolioSerializer):
    """Detailed portfolio serializer with nested data."""
    
    holdings = PortfolioHoldingSerializer(many=True, read_only=True)
    latest_performance = serializers.SerializerMethodField()
    latest_valuation = serializers.SerializerMethodField()
    sector_allocation = serializers.SerializerMethodField()
    geographic_allocation = serializers.SerializerMethodField()
    
    class Meta(PortfolioSerializer.Meta):
        fields = PortfolioSerializer.Meta.fields + [
            'holdings', 'latest_performance', 'latest_valuation',
            'sector_allocation', 'geographic_allocation',
            'regulatory_registrations', 'compliance_restrictions'
        ]
    
    def get_latest_performance(self, obj):
        """Get the latest official performance record."""
        latest = obj.performance_records.filter(
            is_official=True
        ).order_by('-period_end').first()
        return PortfolioPerformanceSerializer(latest).data if latest else None
    
    def get_latest_valuation(self, obj):
        """Get the latest valuation."""
        latest = obj.valuations.order_by('-valuation_date').first()
        if latest:
            return {
                'valuation_date': latest.valuation_date,
                'net_asset_value': latest.net_asset_value,
                'nav_per_unit': latest.nav_per_unit,
                'change_from_previous': latest.calculate_change_from_previous()
            }
        return None
    
    def get_sector_allocation(self, obj):
        """Calculate sector allocation."""
        allocations = []
        holdings = obj.holdings.filter(status='ACTIVE').select_related('investment')
        
        # Group by sector and calculate allocations
        sector_values = {}
        total_value = Decimal('0')
        
        for holding in holdings:
            sectors = holding.investment.sectors if hasattr(holding.investment, 'sectors') else ['Other']
            value_per_sector = holding.current_value / len(sectors) if sectors else holding.current_value
            
            for sector in sectors:
                sector_values[sector] = sector_values.get(sector, Decimal('0')) + value_per_sector
                total_value += value_per_sector
        
        # Convert to percentages
        for sector, value in sector_values.items():
            allocations.append({
                'sector': sector,
                'value': value,
                'percentage': (value / total_value * 100) if total_value > 0 else Decimal('0')
            })
        
        return sorted(allocations, key=lambda x: x['value'], reverse=True)
    
    def get_geographic_allocation(self, obj):
        """Calculate geographic allocation."""
        allocations = []
        holdings = obj.holdings.filter(status='ACTIVE').select_related('investment')
        
        # Group by geography and calculate allocations
        geo_values = {}
        total_value = Decimal('0')
        
        for holding in holdings:
            geographies = holding.investment.geographies if hasattr(holding.investment, 'geographies') else ['Global']
            value_per_geo = holding.current_value / len(geographies) if geographies else holding.current_value
            
            for geography in geographies:
                geo_values[geography] = geo_values.get(geography, Decimal('0')) + value_per_geo
                total_value += value_per_geo
        
        # Convert to percentages
        for geography, value in geo_values.items():
            allocations.append({
                'geography': geography,
                'value': value,
                'percentage': (value / total_value * 100) if total_value > 0 else Decimal('0')
            })
        
        return sorted(allocations, key=lambda x: x['value'], reverse=True)


class PortfolioAnalyticsSerializer(serializers.Serializer):
    """Serializer for portfolio analytics requests and responses."""
    
    # Request parameters
    portfolio_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="List of portfolio IDs to analyze"
    )
    start_date = serializers.DateField(
        required=False,
        help_text="Start date for analysis period"
    )
    end_date = serializers.DateField(
        required=False,
        help_text="End date for analysis period"
    )
    metrics = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of metrics to calculate"
    )
    benchmarks = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of benchmark codes for comparison"
    )
    
    # Response fields
    calculated_metrics = serializers.DictField(read_only=True)
    benchmark_comparisons = serializers.ListField(read_only=True)
    risk_analysis = serializers.DictField(read_only=True)
    attribution_analysis = serializers.DictField(read_only=True)
    correlation_matrix = serializers.ListField(read_only=True)


class PortfolioReportSerializer(BaseSerializer):
    """Serializer for portfolio reports."""
    
    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)
    generated_by_name = serializers.CharField(source='generated_by.get_full_name', read_only=True)
    
    class Meta:
        model = GeneratedReport
        fields = [
            'id', 'portfolio', 'portfolio_name', 'report_type',
            'report_name', 'period_start', 'period_end',
            'generation_date', 'generated_by', 'generated_by_name',
            'file_url', 'file_size', 'format', 'status',
            'parameters', 'metadata', 'created_at'
        ]
        read_only_fields = [
            'id', 'generation_date', 'file_url', 'file_size',
            'status', 'created_at'
        ]


class AlertRuleSerializer(BaseSerializer):
    """Serializer for alert rules."""
    
    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)
    
    class Meta:
        model = AlertRule
        fields = [
            'id', 'portfolio', 'portfolio_name', 'rule_name',
            'rule_type', 'metric', 'operator', 'threshold_value',
            'comparison_period', 'is_active', 'notification_channels',
            'recipients', 'frequency', 'last_triggered',
            'trigger_count', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'last_triggered', 'trigger_count',
            'created_at', 'updated_at'
        ]


class BulkPerformanceCalculationSerializer(serializers.Serializer):
    """Serializer for bulk performance calculation requests."""
    
    portfolio_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of portfolio IDs to calculate performance for"
    )
    calculation_date = serializers.DateField(
        help_text="As-of date for calculations"
    )
    periods = serializers.ListField(
        child=serializers.ChoiceField(choices=[
            'MTD', 'QTD', 'YTD', '1Y', '3Y', '5Y', '10Y', 'ITD'
        ]),
        help_text="Performance periods to calculate"
    )
    calculation_method = serializers.ChoiceField(
        choices=['TIME_WEIGHTED', 'MONEY_WEIGHTED', 'MODIFIED_DIETZ'],
        default='TIME_WEIGHTED',
        help_text="Return calculation methodology"
    )
    include_benchmarks = serializers.BooleanField(
        default=True,
        help_text="Whether to include benchmark comparisons"
    )
    mark_as_official = serializers.BooleanField(
        default=False,
        help_text="Whether to mark these as official performance records"
    )