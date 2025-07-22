"""
Portfolio Performance Calculation Services

Implements various performance calculation methodologies.
"""
from abc import ABC, abstractmethod
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from scipy import optimize
from django.db import transaction
from django.utils import timezone
from ..models import (
    Portfolio, PortfolioHolding, PortfolioPerformance,
    ReturnCalculation, CashFlow
)


class CalculationRegistry:
    """Registry for performance calculation methods."""
    
    _calculators = {}
    
    @classmethod
    def register(cls, name: str, calculator_class):
        """Register a calculator."""
        cls._calculators[name] = calculator_class
    
    @classmethod
    def get(cls, name: str):
        """Get a calculator by name."""
        return cls._calculators.get(name)
    
    @classmethod
    def list_calculators(cls):
        """List all registered calculators."""
        return list(cls._calculators.keys())


class BaseCalculator(ABC):
    """Base class for performance calculators."""
    
    @abstractmethod
    def calculate(
        self,
        beginning_value: Decimal,
        ending_value: Decimal,
        cash_flows: List[Dict[str, Any]],
        period_start: date,
        period_end: date
    ) -> Dict[str, Any]:
        """Calculate performance for the given inputs."""
        pass
    
    def annualize_return(
        self,
        total_return: Decimal,
        period_start: date,
        period_end: date
    ) -> Decimal:
        """Annualize a return over the given period."""
        days = (period_end - period_start).days
        if days <= 0:
            return Decimal('0')
        
        years = Decimal(days) / Decimal('365.25')
        if years <= 1:
            return total_return
        
        # Annualized return = (1 + total_return)^(1/years) - 1
        return Decimal(
            (float(1 + total_return) ** (1 / float(years))) - 1
        )


class TimeWeightedReturnCalculator(BaseCalculator):
    """
    Time-Weighted Return (TWR) Calculator
    
    TWR measures the compound growth rate of a portfolio by eliminating
    the impact of cash flows.
    """
    
    def calculate(
        self,
        beginning_value: Decimal,
        ending_value: Decimal,
        cash_flows: List[Dict[str, Any]],
        period_start: date,
        period_end: date
    ) -> Dict[str, Any]:
        """Calculate time-weighted return."""
        
        if beginning_value == 0:
            return {
                'return': Decimal('0'),
                'annualized_return': Decimal('0'),
                'calculation_steps': {'error': 'Beginning value is zero'}
            }
        
        # Sort cash flows by date
        sorted_flows = sorted(cash_flows, key=lambda x: x['date'])
        
        # Calculate sub-period returns
        sub_periods = []
        current_start = period_start
        current_value = beginning_value
        
        for flow in sorted_flows:
            flow_date = flow['date']
            flow_amount = Decimal(str(flow['amount']))
            
            # Get value just before the flow
            pre_flow_value = current_value  # Simplified - would need valuation
            
            # Calculate sub-period return
            if current_value > 0:
                sub_return = (pre_flow_value - current_value) / current_value
                sub_periods.append({
                    'start': current_start,
                    'end': flow_date,
                    'return': sub_return
                })
            
            # Adjust for cash flow
            current_value = pre_flow_value + flow_amount
            current_start = flow_date
        
        # Final sub-period
        if current_value > 0:
            final_return = (ending_value - current_value) / current_value
            sub_periods.append({
                'start': current_start,
                'end': period_end,
                'return': final_return
            })
        
        # Chain-link the returns
        total_return = Decimal('1')
        for period in sub_periods:
            total_return *= (1 + period['return'])
        
        total_return -= 1
        
        # Annualize
        annualized = self.annualize_return(total_return, period_start, period_end)
        
        return {
            'return': total_return,
            'annualized_return': annualized,
            'calculation_steps': {
                'method': 'time_weighted',
                'sub_periods': len(sub_periods),
                'beginning_value': beginning_value,
                'ending_value': ending_value,
                'total_cash_flows': sum(Decimal(str(f['amount'])) for f in cash_flows)
            }
        }


class MoneyWeightedReturnCalculator(BaseCalculator):
    """
    Money-Weighted Return (MWR) Calculator
    
    MWR is essentially the Internal Rate of Return (IRR) that accounts
    for the timing and size of cash flows.
    """
    
    def calculate(
        self,
        beginning_value: Decimal,
        ending_value: Decimal,
        cash_flows: List[Dict[str, Any]],
        period_start: date,
        period_end: date
    ) -> Dict[str, Any]:
        """Calculate money-weighted return (IRR)."""
        
        # Create cash flow series
        cf_series = [(-beginning_value, period_start)]
        
        # Add intermediate cash flows
        for flow in cash_flows:
            cf_series.append((-Decimal(str(flow['amount'])), flow['date']))
        
        # Add ending value
        cf_series.append((ending_value, period_end))
        
        # Calculate IRR
        irr_calc = IRRCalculator()
        irr_result = irr_calc.calculate_irr(cf_series)
        
        return {
            'return': irr_result['irr'],
            'annualized_return': irr_result['irr'],  # IRR is already annualized
            'calculation_steps': {
                'method': 'money_weighted',
                'cash_flow_count': len(cf_series),
                'beginning_value': beginning_value,
                'ending_value': ending_value,
                'irr_iterations': irr_result.get('iterations', 0)
            }
        }


class ModifiedDietzCalculator(BaseCalculator):
    """
    Modified Dietz Calculator
    
    Approximates money-weighted return without iterative calculations.
    """
    
    def calculate(
        self,
        beginning_value: Decimal,
        ending_value: Decimal,
        cash_flows: List[Dict[str, Any]],
        period_start: date,
        period_end: date
    ) -> Dict[str, Any]:
        """Calculate Modified Dietz return."""
        
        total_days = (period_end - period_start).days
        if total_days == 0:
            return {
                'return': Decimal('0'),
                'annualized_return': Decimal('0'),
                'calculation_steps': {'error': 'Zero-day period'}
            }
        
        # Calculate weighted cash flows
        weighted_flows = Decimal('0')
        total_flows = Decimal('0')
        
        for flow in cash_flows:
            flow_amount = Decimal(str(flow['amount']))
            flow_date = flow['date']
            
            # Weight = fraction of period remaining after flow
            days_remaining = (period_end - flow_date).days
            weight = Decimal(days_remaining) / Decimal(total_days)
            
            weighted_flows += flow_amount * weight
            total_flows += flow_amount
        
        # Modified Dietz formula
        denominator = beginning_value + weighted_flows
        if denominator == 0:
            return {
                'return': Decimal('0'),
                'annualized_return': Decimal('0'),
                'calculation_steps': {'error': 'Zero denominator'}
            }
        
        total_return = (ending_value - beginning_value - total_flows) / denominator
        
        # Annualize
        annualized = self.annualize_return(total_return, period_start, period_end)
        
        return {
            'return': total_return,
            'annualized_return': annualized,
            'calculation_steps': {
                'method': 'modified_dietz',
                'beginning_value': beginning_value,
                'ending_value': ending_value,
                'total_flows': total_flows,
                'weighted_flows': weighted_flows
            }
        }


class IRRCalculator:
    """
    Internal Rate of Return (IRR) Calculator
    """
    
    def calculate_irr(
        self,
        cash_flows: List[Tuple[Decimal, date]],
        guess: float = 0.1
    ) -> Dict[str, Any]:
        """
        Calculate IRR from a series of cash flows.
        
        Args:
            cash_flows: List of (amount, date) tuples
            guess: Initial guess for IRR
        
        Returns:
            Dict with IRR and calculation details
        """
        if not cash_flows:
            return {'irr': Decimal('0'), 'error': 'No cash flows'}
        
        # Sort by date
        sorted_flows = sorted(cash_flows, key=lambda x: x[1])
        start_date = sorted_flows[0][1]
        
        # Convert to time-weighted cash flows
        amounts = []
        days = []
        
        for amount, flow_date in sorted_flows:
            amounts.append(float(amount))
            days.append((flow_date - start_date).days)
        
        # NPV function for root finding
        def npv(rate):
            return sum(
                amount / ((1 + rate) ** (day / 365.25))
                for amount, day in zip(amounts, days)
            )
        
        try:
            # Use scipy to find IRR
            result = optimize.root_scalar(
                npv,
                bracket=[-0.99, 10],
                method='brentq',
                xtol=1e-6
            )
            
            irr = Decimal(str(result.root))
            
            return {
                'irr': irr,
                'converged': result.converged,
                'iterations': result.iterations,
                'function_calls': result.function_calls
            }
            
        except Exception as e:
            return {
                'irr': Decimal('0'),
                'error': str(e),
                'converged': False
            }


class MOICCalculator:
    """
    Multiple on Invested Capital (MOIC) Calculator
    """
    
    def calculate(
        self,
        total_value: Decimal,
        total_invested: Decimal
    ) -> Dict[str, Any]:
        """Calculate MOIC."""
        if total_invested == 0:
            return {
                'moic': Decimal('0'),
                'error': 'No invested capital'
            }
        
        moic = total_value / total_invested
        
        return {
            'moic': moic,
            'total_value': total_value,
            'total_invested': total_invested
        }


class DPICalculator:
    """
    Distributions to Paid-In (DPI) Calculator
    """
    
    def calculate(
        self,
        total_distributions: Decimal,
        paid_in_capital: Decimal
    ) -> Dict[str, Any]:
        """Calculate DPI."""
        if paid_in_capital == 0:
            return {
                'dpi': Decimal('0'),
                'error': 'No paid-in capital'
            }
        
        dpi = total_distributions / paid_in_capital
        
        return {
            'dpi': dpi,
            'total_distributions': total_distributions,
            'paid_in_capital': paid_in_capital
        }


class TVPICalculator:
    """
    Total Value to Paid-In (TVPI) Calculator
    """
    
    def calculate(
        self,
        total_value: Decimal,
        total_distributions: Decimal,
        paid_in_capital: Decimal
    ) -> Dict[str, Any]:
        """Calculate TVPI."""
        if paid_in_capital == 0:
            return {
                'tvpi': Decimal('0'),
                'error': 'No paid-in capital'
            }
        
        tvpi = (total_value + total_distributions) / paid_in_capital
        
        return {
            'tvpi': tvpi,
            'total_value': total_value,
            'total_distributions': total_distributions,
            'paid_in_capital': paid_in_capital
        }


class PerformanceCalculationService:
    """
    Main service for calculating and storing portfolio performance.
    """
    
    def __init__(self):
        self.registry = CalculationRegistry()
    
    def calculate_performance(
        self,
        portfolio: Portfolio,
        periods: List[str],
        as_of_date: date,
        include_holdings: bool = False
    ) -> Dict[str, Any]:
        """
        Calculate performance for specified periods.
        
        Args:
            portfolio: Portfolio instance
            periods: List of period codes (YTD, 1Y, 3Y, etc.)
            as_of_date: Calculation date
            include_holdings: Whether to include holding-level performance
        
        Returns:
            Dict with performance data for each period
        """
        results = {
            'portfolio_id': str(portfolio.id),
            'portfolio_name': portfolio.name,
            'as_of_date': as_of_date,
            'base_currency': portfolio.base_currency,
            'periods': {}
        }
        
        for period_code in periods:
            period_start = self._get_period_start(period_code, as_of_date, portfolio)
            
            # Get performance data
            perf_data = self._calculate_period_performance(
                portfolio, period_start, as_of_date
            )
            
            results['periods'][period_code] = perf_data
        
        # Add current metrics
        results['current_metrics'] = {
            'net_asset_value': portfolio.net_asset_value,
            'committed_capital': portfolio.committed_capital,
            'called_capital': portfolio.called_capital,
            'distributed_capital': portfolio.distributed_capital,
            'tvpi': portfolio.total_value_to_paid_in,
            'dpi': portfolio.distributions_to_paid_in,
            'rvpi': portfolio.residual_value_to_paid_in
        }
        
        # Add holdings performance if requested
        if include_holdings:
            results['holdings'] = self._calculate_holdings_performance(
                portfolio, as_of_date
            )
        
        return results
    
    @transaction.atomic
    def calculate_and_store_performance(
        self,
        portfolio: Portfolio,
        calculation_date: date,
        periods: List[str],
        calculation_method: str = 'TIME_WEIGHTED',
        include_benchmarks: bool = True,
        mark_as_official: bool = False,
        **kwargs
    ) -> List[PortfolioPerformance]:
        """
        Calculate and store performance records in the database.
        """
        created_records = []
        
        for period_code in periods:
            period_start = self._get_period_start(
                period_code, calculation_date, portfolio
            )
            
            # Get cash flows for the period
            cash_flows = self._get_cash_flows(
                portfolio, period_start, calculation_date
            )
            
            # Get valuations
            beginning_value = self._get_portfolio_value(portfolio, period_start)
            ending_value = self._get_portfolio_value(portfolio, calculation_date)
            
            # Calculate performance
            calculator = self.registry.get(calculation_method.lower())()
            result = calculator.calculate(
                beginning_value=beginning_value,
                ending_value=ending_value,
                cash_flows=cash_flows,
                period_start=period_start,
                period_end=calculation_date
            )
            
            # Create performance record
            performance = PortfolioPerformance.objects.create(
                portfolio=portfolio,
                period_type=period_code,
                period_start=period_start,
                period_end=calculation_date,
                gross_return=result['return'],
                net_return=self._calculate_net_return(
                    result['return'], portfolio, period_start, calculation_date
                ),
                gross_irr=result.get('annualized_return'),
                net_irr=self._calculate_net_return(
                    result.get('annualized_return', Decimal('0')),
                    portfolio, period_start, calculation_date
                ),
                total_contributions=sum(
                    Decimal(str(cf['amount'])) for cf in cash_flows
                    if Decimal(str(cf['amount'])) > 0
                ),
                total_distributions=abs(sum(
                    Decimal(str(cf['amount'])) for cf in cash_flows
                    if Decimal(str(cf['amount'])) < 0
                )),
                beginning_value=beginning_value,
                ending_value=ending_value,
                calculation_method=calculation_method,
                calculation_parameters=result.get('calculation_steps', {}),
                is_official=mark_as_official
            )
            
            created_records.append(performance)
            
            # Create detailed calculation record
            ReturnCalculation.objects.create(
                portfolio=portfolio,
                performance_record=performance,
                calculation_type=calculation_method,
                period_start=period_start,
                period_end=calculation_date,
                cash_flows=cash_flows,
                beginning_value=beginning_value,
                ending_value=ending_value,
                calculated_return=result['return'],
                annualized_return=result.get('annualized_return'),
                calculation_steps=result.get('calculation_steps', {})
            )
        
        return created_records
    
    def _get_period_start(
        self,
        period_code: str,
        as_of_date: date,
        portfolio: Portfolio
    ) -> date:
        """Get the start date for a period code."""
        if period_code == 'MTD':
            return as_of_date.replace(day=1)
        elif period_code == 'QTD':
            quarter = (as_of_date.month - 1) // 3
            return date(as_of_date.year, quarter * 3 + 1, 1)
        elif period_code == 'YTD':
            return date(as_of_date.year, 1, 1)
        elif period_code == '1Y':
            return as_of_date - timedelta(days=365)
        elif period_code == '3Y':
            return as_of_date.replace(year=as_of_date.year - 3)
        elif period_code == '5Y':
            return as_of_date.replace(year=as_of_date.year - 5)
        elif period_code == '10Y':
            return as_of_date.replace(year=as_of_date.year - 10)
        elif period_code == 'ITD':
            return portfolio.inception_date
        else:
            raise ValueError(f"Unknown period code: {period_code}")
    
    def _get_cash_flows(
        self,
        portfolio: Portfolio,
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """Get cash flows for a portfolio during a period."""
        # This would query the CashFlow model
        # For now, return empty list
        return []
    
    def _get_portfolio_value(
        self,
        portfolio: Portfolio,
        as_of_date: date
    ) -> Decimal:
        """Get portfolio value as of a specific date."""
        # Get the most recent valuation on or before the date
        valuation = portfolio.valuations.filter(
            valuation_date__lte=as_of_date
        ).order_by('-valuation_date').first()
        
        return valuation.net_asset_value if valuation else Decimal('0')
    
    def _calculate_net_return(
        self,
        gross_return: Decimal,
        portfolio: Portfolio,
        start_date: date,
        end_date: date
    ) -> Decimal:
        """Calculate net return after fees."""
        # Simplified calculation - deduct management fee
        years = Decimal((end_date - start_date).days) / Decimal('365.25')
        mgmt_fee_impact = portfolio.management_fee_percentage / 100 * years
        
        return gross_return - mgmt_fee_impact
    
    def _calculate_period_performance(
        self,
        portfolio: Portfolio,
        period_start: date,
        period_end: date
    ) -> Dict[str, Any]:
        """Calculate performance metrics for a period."""
        # Get the most recent official performance record if available
        existing = PortfolioPerformance.objects.filter(
            portfolio=portfolio,
            period_start=period_start,
            period_end=period_end,
            is_official=True
        ).first()
        
        if existing:
            return {
                'gross_return': existing.gross_return,
                'net_return': existing.net_return,
                'gross_irr': existing.gross_irr,
                'net_irr': existing.net_irr,
                'from_cache': True
            }
        
        # Calculate if not cached
        # Simplified calculation for now
        return {
            'gross_return': Decimal('0.08'),  # Placeholder
            'net_return': Decimal('0.06'),    # Placeholder
            'gross_irr': Decimal('0.10'),     # Placeholder
            'net_irr': Decimal('0.08'),       # Placeholder
            'from_cache': False
        }
    
    def _calculate_holdings_performance(
        self,
        portfolio: Portfolio,
        as_of_date: date
    ) -> List[Dict[str, Any]]:
        """Calculate performance for individual holdings."""
        holdings_data = []
        
        for holding in portfolio.holdings.filter(status='ACTIVE'):
            holdings_data.append({
                'holding_id': str(holding.id),
                'investment_name': holding.investment.name,
                'invested_amount': holding.invested_amount,
                'current_value': holding.current_value,
                'total_distributions': holding.total_distributions,
                'unrealized_value': holding.unrealized_value,
                'multiple': holding.multiple_on_invested_capital,
                'gross_irr': holding.gross_irr,
                'net_irr': holding.net_irr
            })
        
        return holdings_data