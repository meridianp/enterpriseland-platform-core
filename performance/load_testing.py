"""
Load Testing Framework

Comprehensive load testing framework for performance validation.
"""
import asyncio
import aiohttp
import time
import random
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from urllib.parse import urljoin
import numpy as np
from locust import HttpUser, task, between, events
from locust.env import Environment
from locust.stats import stats_printer, stats_history
from locust.log import setup_logging

logger = logging.getLogger(__name__)


@dataclass
class LoadTestScenario:
    """Defines a load test scenario."""
    name: str
    duration: timedelta
    users: int
    spawn_rate: float  # Users per second
    endpoints: List[Dict[str, Any]]
    think_time: Tuple[float, float] = (1, 3)  # Min/max seconds between requests
    
    
@dataclass
class LoadTestResult:
    """Results from a load test run."""
    scenario_name: str
    start_time: datetime
    end_time: datetime
    total_requests: int
    successful_requests: int
    failed_requests: int
    response_times: List[float]
    error_details: List[Dict[str, Any]] = field(default_factory=list)
    throughput: float = 0.0  # Requests per second
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def percentiles(self) -> Dict[str, float]:
        """Calculate response time percentiles."""
        if not self.response_times:
            return {'p50': 0, 'p95': 0, 'p99': 0}
        
        sorted_times = sorted(self.response_times)
        n = len(sorted_times)
        
        return {
            'p50': sorted_times[int(n * 0.5)],
            'p95': sorted_times[int(n * 0.95)],
            'p99': sorted_times[int(n * 0.99)],
            'avg': statistics.mean(sorted_times),
            'min': min(sorted_times),
            'max': max(sorted_times)
        }


class LoadTestFramework:
    """
    Main load testing framework for EnterpriseLand platform.
    
    Features:
    - Multiple load patterns (constant, ramp-up, spike, stress)
    - Real-world scenario simulation
    - Performance metrics collection
    - SLA validation
    - Detailed reporting
    """
    
    # Predefined test scenarios
    SCENARIOS = {
        'baseline': LoadTestScenario(
            name='Baseline Load Test',
            duration=timedelta(minutes=10),
            users=50,
            spawn_rate=5,
            endpoints=[
                {'path': '/api/portfolios/', 'method': 'GET', 'weight': 40},
                {'path': '/api/portfolios/{id}/', 'method': 'GET', 'weight': 30},
                {'path': '/api/leads/', 'method': 'GET', 'weight': 20},
                {'path': '/api/market-intelligence/', 'method': 'GET', 'weight': 10},
            ]
        ),
        'peak_load': LoadTestScenario(
            name='Peak Load Test',
            duration=timedelta(minutes=30),
            users=500,
            spawn_rate=10,
            endpoints=[
                {'path': '/api/portfolios/', 'method': 'GET', 'weight': 25},
                {'path': '/api/portfolios/{id}/performance/', 'method': 'GET', 'weight': 20},
                {'path': '/api/portfolios/{id}/analytics/', 'method': 'GET', 'weight': 15},
                {'path': '/api/leads/', 'method': 'GET', 'weight': 15},
                {'path': '/api/leads/scoring/', 'method': 'POST', 'weight': 10},
                {'path': '/api/market-intelligence/targets/', 'method': 'GET', 'weight': 10},
                {'path': '/api/deals/', 'method': 'GET', 'weight': 5},
            ]
        ),
        'stress_test': LoadTestScenario(
            name='Stress Test',
            duration=timedelta(minutes=60),
            users=1000,
            spawn_rate=20,
            endpoints=[
                {'path': '/api/portfolios/', 'method': 'GET', 'weight': 20},
                {'path': '/api/portfolios/{id}/performance/', 'method': 'GET', 'weight': 20},
                {'path': '/api/portfolios/analytics/calculate/', 'method': 'POST', 'weight': 15},
                {'path': '/api/reports/generate/', 'method': 'POST', 'weight': 10},
                {'path': '/api/leads/', 'method': 'GET', 'weight': 10},
                {'path': '/api/leads/scoring/', 'method': 'POST', 'weight': 10},
                {'path': '/api/market-intelligence/analyze/', 'method': 'POST', 'weight': 10},
                {'path': '/api/files/upload/', 'method': 'POST', 'weight': 5},
            ]
        ),
        'endurance_test': LoadTestScenario(
            name='Endurance Test',
            duration=timedelta(hours=4),
            users=200,
            spawn_rate=5,
            endpoints=[
                {'path': '/api/portfolios/', 'method': 'GET', 'weight': 30},
                {'path': '/api/portfolios/{id}/', 'method': 'GET', 'weight': 25},
                {'path': '/api/leads/', 'method': 'GET', 'weight': 20},
                {'path': '/api/market-intelligence/', 'method': 'GET', 'weight': 15},
                {'path': '/api/contacts/', 'method': 'GET', 'weight': 10},
            ]
        )
    }
    
    def __init__(self, base_url: str, auth_token: Optional[str] = None):
        self.base_url = base_url
        self.auth_token = auth_token
        self.session = None
        self.results = []
    
    async def run_scenario(
        self,
        scenario: LoadTestScenario,
        progress_callback: Optional[Callable] = None
    ) -> LoadTestResult:
        """
        Run a load test scenario.
        
        Args:
            scenario: Load test scenario to run
            progress_callback: Optional callback for progress updates
            
        Returns:
            LoadTestResult object
        """
        logger.info(f"Starting load test scenario: {scenario.name}")
        
        # Initialize result tracking
        result = LoadTestResult(
            scenario_name=scenario.name,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_requests=0,
            successful_requests=0,
            failed_requests=0,
            response_times=[]
        )
        
        # Create async session
        headers = {}
        if self.auth_token:
            headers['Authorization'] = f'Bearer {self.auth_token}'
        
        async with aiohttp.ClientSession(headers=headers) as session:
            self.session = session
            
            # Start virtual users
            tasks = []
            for i in range(scenario.users):
                # Stagger user starts based on spawn rate
                delay = i / scenario.spawn_rate
                task = asyncio.create_task(
                    self._run_virtual_user(scenario, result, delay)
                )
                tasks.append(task)
            
            # Monitor progress
            monitor_task = asyncio.create_task(
                self._monitor_progress(
                    scenario, result, progress_callback
                )
            )
            
            # Wait for scenario duration
            await asyncio.sleep(scenario.duration.total_seconds())
            
            # Stop all tasks
            for task in tasks:
                task.cancel()
            monitor_task.cancel()
            
            # Wait for tasks to complete
            await asyncio.gather(*tasks, monitor_task, return_exceptions=True)
        
        # Finalize results
        result.end_time = datetime.now()
        duration_seconds = (result.end_time - result.start_time).total_seconds()
        result.throughput = result.total_requests / duration_seconds if duration_seconds > 0 else 0
        
        logger.info(f"Load test completed: {result.total_requests} requests, "
                   f"{result.success_rate:.2f}% success rate")
        
        return result
    
    async def _run_virtual_user(
        self,
        scenario: LoadTestScenario,
        result: LoadTestResult,
        initial_delay: float
    ) -> None:
        """Run a single virtual user."""
        # Initial delay for spawn rate
        await asyncio.sleep(initial_delay)
        
        while True:
            try:
                # Select endpoint based on weights
                endpoint = self._select_weighted_endpoint(scenario.endpoints)
                
                # Make request
                start_time = time.time()
                success = await self._make_request(endpoint)
                response_time = time.time() - start_time
                
                # Update results
                result.total_requests += 1
                result.response_times.append(response_time)
                
                if success:
                    result.successful_requests += 1
                else:
                    result.failed_requests += 1
                
                # Think time
                think_time = random.uniform(*scenario.think_time)
                await asyncio.sleep(think_time)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Virtual user error: {e}")
                result.error_details.append({
                    'timestamp': datetime.now(),
                    'error': str(e),
                    'endpoint': endpoint.get('path', 'unknown')
                })
    
    def _select_weighted_endpoint(self, endpoints: List[Dict]) -> Dict:
        """Select an endpoint based on weights."""
        weights = [ep.get('weight', 1) for ep in endpoints]
        return random.choices(endpoints, weights=weights)[0]
    
    async def _make_request(self, endpoint: Dict) -> bool:
        """Make an HTTP request to an endpoint."""
        try:
            method = endpoint.get('method', 'GET')
            path = endpoint['path']
            
            # Handle dynamic path parameters
            if '{id}' in path:
                # In real scenario, would use actual IDs
                path = path.replace('{id}', str(random.randint(1, 100)))
            
            url = urljoin(self.base_url, path)
            
            # Prepare request data
            data = None
            if method == 'POST':
                data = self._generate_request_data(endpoint)
            
            # Make request
            async with self.session.request(method, url, json=data) as response:
                return response.status < 400
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return False
    
    def _generate_request_data(self, endpoint: Dict) -> Dict:
        """Generate request data for POST endpoints."""
        path = endpoint['path']
        
        if 'scoring' in path:
            return {
                'lead_ids': [random.randint(1, 1000) for _ in range(10)],
                'model_id': 'default'
            }
        elif 'analytics' in path:
            return {
                'portfolio_ids': [str(random.randint(1, 50))],
                'metrics': ['irr', 'moic', 'dpi'],
                'start_date': '2024-01-01',
                'end_date': '2024-12-31'
            }
        elif 'generate' in path:
            return {
                'report_type': 'ilpa_quarterly',
                'period_start': '2024-01-01',
                'period_end': '2024-03-31',
                'format': 'pdf'
            }
        
        return {}
    
    async def _monitor_progress(
        self,
        scenario: LoadTestScenario,
        result: LoadTestResult,
        callback: Optional[Callable]
    ) -> None:
        """Monitor test progress and report metrics."""
        while True:
            try:
                await asyncio.sleep(5)  # Report every 5 seconds
                
                if callback and result.response_times:
                    metrics = {
                        'elapsed_time': (datetime.now() - result.start_time).total_seconds(),
                        'total_requests': result.total_requests,
                        'success_rate': result.success_rate,
                        'current_rps': result.throughput,
                        'response_times': result.percentiles
                    }
                    callback(metrics)
                    
            except asyncio.CancelledError:
                break
    
    def run_sla_validation(
        self,
        scenario_name: str = 'baseline',
        sla_targets: Optional[Dict[str, float]] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Run load test and validate against SLA targets.
        
        Args:
            scenario_name: Name of scenario to run
            sla_targets: SLA targets to validate against
            
        Returns:
            Tuple of (passed, detailed_results)
        """
        if sla_targets is None:
            sla_targets = {
                'response_time_p95': 2.0,
                'response_time_p99': 5.0,
                'success_rate': 99.9,
                'throughput': 100.0
            }
        
        # Run scenario
        scenario = self.SCENARIOS.get(scenario_name)
        if not scenario:
            raise ValueError(f"Unknown scenario: {scenario_name}")
        
        # Run test synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.run_scenario(scenario))
        loop.close()
        
        # Validate against SLAs
        percentiles = result.percentiles
        validation_results = {
            'passed': True,
            'scenario': scenario_name,
            'metrics': {
                'response_time_p95': {
                    'target': sla_targets.get('response_time_p95', 2.0),
                    'actual': percentiles.get('p95', 0),
                    'passed': percentiles.get('p95', 0) <= sla_targets.get('response_time_p95', 2.0)
                },
                'response_time_p99': {
                    'target': sla_targets.get('response_time_p99', 5.0),
                    'actual': percentiles.get('p99', 0),
                    'passed': percentiles.get('p99', 0) <= sla_targets.get('response_time_p99', 5.0)
                },
                'success_rate': {
                    'target': sla_targets.get('success_rate', 99.9),
                    'actual': result.success_rate,
                    'passed': result.success_rate >= sla_targets.get('success_rate', 99.9)
                },
                'throughput': {
                    'target': sla_targets.get('throughput', 100.0),
                    'actual': result.throughput,
                    'passed': result.throughput >= sla_targets.get('throughput', 100.0)
                }
            },
            'summary': {
                'total_requests': result.total_requests,
                'duration_seconds': (result.end_time - result.start_time).total_seconds(),
                'errors': len(result.error_details)
            }
        }
        
        # Check if all SLAs passed
        validation_results['passed'] = all(
            metric['passed'] for metric in validation_results['metrics'].values()
        )
        
        return validation_results['passed'], validation_results
    
    def generate_load_test_report(self, results: List[LoadTestResult]) -> Dict[str, Any]:
        """
        Generate comprehensive load test report.
        
        Args:
            results: List of load test results
            
        Returns:
            Detailed report dictionary
        """
        report = {
            'generated_at': datetime.now(),
            'total_scenarios': len(results),
            'scenarios': [],
            'overall_metrics': {},
            'recommendations': []
        }
        
        all_response_times = []
        total_requests = 0
        total_failures = 0
        
        for result in results:
            all_response_times.extend(result.response_times)
            total_requests += result.total_requests
            total_failures += result.failed_requests
            
            scenario_report = {
                'name': result.scenario_name,
                'duration': (result.end_time - result.start_time).total_seconds(),
                'total_requests': result.total_requests,
                'success_rate': result.success_rate,
                'throughput': result.throughput,
                'response_times': result.percentiles,
                'errors': len(result.error_details)
            }
            report['scenarios'].append(scenario_report)
        
        # Calculate overall metrics
        if all_response_times:
            sorted_times = sorted(all_response_times)
            n = len(sorted_times)
            
            report['overall_metrics'] = {
                'total_requests': total_requests,
                'total_failures': total_failures,
                'overall_success_rate': ((total_requests - total_failures) / total_requests * 100) if total_requests > 0 else 0,
                'response_times': {
                    'p50': sorted_times[int(n * 0.5)],
                    'p95': sorted_times[int(n * 0.95)],
                    'p99': sorted_times[int(n * 0.99)],
                    'avg': statistics.mean(sorted_times),
                    'min': min(sorted_times),
                    'max': max(sorted_times)
                }
            }
        
        # Generate recommendations
        report['recommendations'] = self._generate_recommendations(report)
        
        return report
    
    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate performance recommendations based on test results."""
        recommendations = []
        
        metrics = report.get('overall_metrics', {})
        response_times = metrics.get('response_times', {})
        
        # Check response times
        if response_times.get('p95', 0) > 2.0:
            recommendations.append(
                "Response time P95 exceeds 2 seconds. Consider optimizing slow endpoints, "
                "implementing caching, or scaling backend services."
            )
        
        if response_times.get('p99', 0) > 5.0:
            recommendations.append(
                "Response time P99 exceeds 5 seconds. Investigate timeout issues and "
                "consider implementing circuit breakers for external dependencies."
            )
        
        # Check success rate
        success_rate = metrics.get('overall_success_rate', 100)
        if success_rate < 99.9:
            recommendations.append(
                f"Success rate ({success_rate:.2f}%) below 99.9% SLA. "
                "Review error logs and implement retry mechanisms."
            )
        
        # Check for specific scenario issues
        for scenario in report.get('scenarios', []):
            if scenario['throughput'] < 100:
                recommendations.append(
                    f"{scenario['name']} throughput ({scenario['throughput']:.2f} RPS) "
                    "below target. Consider horizontal scaling or connection pooling."
                )
        
        if not recommendations:
            recommendations.append("All performance metrics within acceptable ranges.")
        
        return recommendations


class EnterpriseLandUser(HttpUser):
    """
    Locust user class for EnterpriseLand platform testing.
    """
    wait_time = between(1, 3)
    
    def on_start(self):
        """Login and set authentication token."""
        response = self.client.post("/api/auth/login/", json={
            "email": "test@example.com",
            "password": "testpass123"
        })
        if response.status_code == 200:
            data = response.json()
            self.client.headers['Authorization'] = f"Bearer {data['access_token']}"
    
    @task(40)
    def view_portfolios(self):
        """View portfolio list."""
        self.client.get("/api/portfolios/")
    
    @task(30)
    def view_portfolio_detail(self):
        """View portfolio details."""
        portfolio_id = random.randint(1, 100)
        self.client.get(f"/api/portfolios/{portfolio_id}/")
    
    @task(20)
    def view_portfolio_performance(self):
        """View portfolio performance."""
        portfolio_id = random.randint(1, 100)
        self.client.get(f"/api/portfolios/{portfolio_id}/performance/")
    
    @task(10)
    def calculate_analytics(self):
        """Calculate portfolio analytics."""
        self.client.post("/api/portfolios/analytics/calculate/", json={
            "portfolio_ids": [str(random.randint(1, 50)) for _ in range(5)],
            "metrics": ["irr", "moic", "dpi"],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31"
        })


def run_locust_test(
    host: str,
    users: int = 100,
    spawn_rate: int = 10,
    run_time: int = 300
):
    """
    Run a Locust load test programmatically.
    
    Args:
        host: Target host URL
        users: Number of users to simulate
        spawn_rate: Users to spawn per second
        run_time: Test duration in seconds
    """
    # Setup logging
    setup_logging("INFO", None)
    
    # Create environment
    env = Environment(user_classes=[EnterpriseLandUser])
    env.create_local_runner()
    
    # Start test
    env.runner.start(users, spawn_rate=spawn_rate)
    
    # Run for specified time
    time.sleep(run_time)
    
    # Stop test
    env.runner.quit()
    
    # Print statistics
    stats_printer(env.stats)
    
    return env.stats