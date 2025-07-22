"""
Auto-scaling Configuration and Management

Handles automatic scaling based on performance metrics.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import statistics

from django.conf import settings
from django.core.cache import cache
from kubernetes import client, config
from prometheus_client import Gauge

logger = logging.getLogger(__name__)


# Prometheus metrics for scaling
current_replicas_gauge = Gauge(
    'autoscaling_current_replicas',
    'Current number of replicas',
    ['service', 'deployment']
)

scaling_events_gauge = Gauge(
    'autoscaling_events_total',
    'Total number of scaling events',
    ['service', 'direction']
)


class ScalingDirection(Enum):
    """Scaling direction."""
    UP = "up"
    DOWN = "down"
    NONE = "none"


@dataclass
class ScalingPolicy:
    """Auto-scaling policy configuration."""
    service_name: str
    min_replicas: int = 2
    max_replicas: int = 10
    
    # CPU thresholds
    cpu_scale_up_threshold: float = 70.0  # Percentage
    cpu_scale_down_threshold: float = 30.0
    
    # Memory thresholds
    memory_scale_up_threshold: float = 80.0  # Percentage
    memory_scale_down_threshold: float = 40.0
    
    # Response time thresholds
    response_time_scale_up_threshold: float = 2.0  # Seconds
    response_time_scale_down_threshold: float = 0.5
    
    # Request rate thresholds
    request_rate_scale_up_threshold: float = 100.0  # Requests per second per replica
    request_rate_scale_down_threshold: float = 20.0
    
    # Scaling behavior
    scale_up_cooldown: timedelta = timedelta(minutes=3)
    scale_down_cooldown: timedelta = timedelta(minutes=10)
    scale_up_increment: int = 2
    scale_down_increment: int = 1
    
    # Stability window
    stability_window: timedelta = timedelta(minutes=5)
    required_breach_percentage: float = 60.0  # % of data points that must breach


@dataclass
class ScalingMetrics:
    """Current metrics for scaling decisions."""
    timestamp: datetime
    cpu_usage: float
    memory_usage: float
    response_time_p95: float
    request_rate: float
    current_replicas: int
    pending_requests: int = 0
    error_rate: float = 0.0


@dataclass
class ScalingDecision:
    """Scaling decision result."""
    direction: ScalingDirection
    current_replicas: int
    target_replicas: int
    reason: str
    metrics: ScalingMetrics
    confidence: float  # 0-100


class AutoScalingManager:
    """
    Manages auto-scaling for EnterpriseLand platform services.
    
    Features:
    - Multi-metric scaling decisions
    - Predictive scaling
    - Cooldown periods
    - Gradual scaling
    - Cost optimization
    """
    
    # Default policies for different services
    DEFAULT_POLICIES = {
        'api': ScalingPolicy(
            service_name='api',
            min_replicas=3,
            max_replicas=20,
            cpu_scale_up_threshold=70.0,
            response_time_scale_up_threshold=2.0
        ),
        'worker': ScalingPolicy(
            service_name='worker',
            min_replicas=2,
            max_replicas=10,
            cpu_scale_up_threshold=80.0,
            memory_scale_up_threshold=85.0
        ),
        'analytics': ScalingPolicy(
            service_name='analytics',
            min_replicas=1,
            max_replicas=5,
            cpu_scale_up_threshold=60.0,
            response_time_scale_up_threshold=5.0
        )
    }
    
    def __init__(self):
        self.policies = self._load_policies()
        self.metrics_history = {}
        self.scaling_history = {}
        self.kubernetes_client = self._init_kubernetes_client()
    
    def _load_policies(self) -> Dict[str, ScalingPolicy]:
        """Load scaling policies from configuration."""
        policies = {}
        
        # Load from settings or use defaults
        configured_policies = getattr(settings, 'AUTOSCALING_POLICIES', {})
        
        for service, default_policy in self.DEFAULT_POLICIES.items():
            if service in configured_policies:
                # Merge with configured values
                policy_dict = default_policy.__dict__.copy()
                policy_dict.update(configured_policies[service])
                policies[service] = ScalingPolicy(**policy_dict)
            else:
                policies[service] = default_policy
        
        return policies
    
    def _init_kubernetes_client(self) -> Optional[client.AppsV1Api]:
        """Initialize Kubernetes client if available."""
        try:
            # Try in-cluster config first
            config.load_incluster_config()
        except:
            try:
                # Fall back to kubeconfig
                config.load_kube_config()
            except:
                logger.warning("Kubernetes client not available")
                return None
        
        return client.AppsV1Api()
    
    def evaluate_scaling(
        self,
        service_name: str,
        current_metrics: ScalingMetrics
    ) -> ScalingDecision:
        """
        Evaluate whether scaling is needed.
        
        Args:
            service_name: Name of the service
            current_metrics: Current performance metrics
            
        Returns:
            ScalingDecision object
        """
        policy = self.policies.get(service_name)
        if not policy:
            raise ValueError(f"No scaling policy for service: {service_name}")
        
        # Store metrics in history
        self._store_metrics(service_name, current_metrics)
        
        # Check if we're in cooldown period
        if self._is_in_cooldown(service_name):
            return ScalingDecision(
                direction=ScalingDirection.NONE,
                current_replicas=current_metrics.current_replicas,
                target_replicas=current_metrics.current_replicas,
                reason="In cooldown period",
                metrics=current_metrics,
                confidence=0.0
            )
        
        # Evaluate each metric
        scale_up_signals = []
        scale_down_signals = []
        
        # CPU evaluation
        if current_metrics.cpu_usage > policy.cpu_scale_up_threshold:
            scale_up_signals.append(('cpu', current_metrics.cpu_usage))
        elif current_metrics.cpu_usage < policy.cpu_scale_down_threshold:
            scale_down_signals.append(('cpu', current_metrics.cpu_usage))
        
        # Memory evaluation
        if current_metrics.memory_usage > policy.memory_scale_up_threshold:
            scale_up_signals.append(('memory', current_metrics.memory_usage))
        elif current_metrics.memory_usage < policy.memory_scale_down_threshold:
            scale_down_signals.append(('memory', current_metrics.memory_usage))
        
        # Response time evaluation
        if current_metrics.response_time_p95 > policy.response_time_scale_up_threshold:
            scale_up_signals.append(('response_time', current_metrics.response_time_p95))
        elif current_metrics.response_time_p95 < policy.response_time_scale_down_threshold:
            scale_down_signals.append(('response_time', current_metrics.response_time_p95))
        
        # Request rate evaluation (per replica)
        request_rate_per_replica = (
            current_metrics.request_rate / current_metrics.current_replicas
            if current_metrics.current_replicas > 0 else 0
        )
        if request_rate_per_replica > policy.request_rate_scale_up_threshold:
            scale_up_signals.append(('request_rate', request_rate_per_replica))
        elif request_rate_per_replica < policy.request_rate_scale_down_threshold:
            scale_down_signals.append(('request_rate', request_rate_per_replica))
        
        # Make scaling decision
        if scale_up_signals and not scale_down_signals:
            return self._decide_scale_up(
                service_name, policy, current_metrics, scale_up_signals
            )
        elif scale_down_signals and not scale_up_signals:
            return self._decide_scale_down(
                service_name, policy, current_metrics, scale_down_signals
            )
        else:
            return ScalingDecision(
                direction=ScalingDirection.NONE,
                current_replicas=current_metrics.current_replicas,
                target_replicas=current_metrics.current_replicas,
                reason="Mixed signals or no clear trend",
                metrics=current_metrics,
                confidence=30.0
            )
    
    def _decide_scale_up(
        self,
        service_name: str,
        policy: ScalingPolicy,
        metrics: ScalingMetrics,
        signals: List[Tuple[str, float]]
    ) -> ScalingDecision:
        """Decide on scale up action."""
        # Check if we've hit max replicas
        if metrics.current_replicas >= policy.max_replicas:
            return ScalingDecision(
                direction=ScalingDirection.NONE,
                current_replicas=metrics.current_replicas,
                target_replicas=metrics.current_replicas,
                reason="Already at maximum replicas",
                metrics=metrics,
                confidence=0.0
            )
        
        # Calculate confidence based on number and strength of signals
        confidence = min(len(signals) * 25, 100)
        
        # Check stability window
        if not self._is_trend_stable(service_name, 'up'):
            confidence *= 0.7
        
        # Calculate target replicas
        target_replicas = min(
            metrics.current_replicas + policy.scale_up_increment,
            policy.max_replicas
        )
        
        # Consider predictive scaling
        predicted_load = self._predict_future_load(service_name)
        if predicted_load > 1.5:  # 50% increase expected
            target_replicas = min(
                target_replicas + 1,
                policy.max_replicas
            )
            confidence = min(confidence + 10, 100)
        
        reason = f"Scale up triggered by: {', '.join([s[0] for s in signals])}"
        
        return ScalingDecision(
            direction=ScalingDirection.UP,
            current_replicas=metrics.current_replicas,
            target_replicas=target_replicas,
            reason=reason,
            metrics=metrics,
            confidence=confidence
        )
    
    def _decide_scale_down(
        self,
        service_name: str,
        policy: ScalingPolicy,
        metrics: ScalingMetrics,
        signals: List[Tuple[str, float]]
    ) -> ScalingDecision:
        """Decide on scale down action."""
        # Check if we've hit min replicas
        if metrics.current_replicas <= policy.min_replicas:
            return ScalingDecision(
                direction=ScalingDirection.NONE,
                current_replicas=metrics.current_replicas,
                target_replicas=metrics.current_replicas,
                reason="Already at minimum replicas",
                metrics=metrics,
                confidence=0.0
            )
        
        # More conservative for scale down
        confidence = min(len(signals) * 20, 80)
        
        # Check stability window (longer for scale down)
        if not self._is_trend_stable(service_name, 'down', window_minutes=10):
            confidence *= 0.5
        
        # Check error rate - don't scale down if errors are high
        if metrics.error_rate > 1.0:
            return ScalingDecision(
                direction=ScalingDirection.NONE,
                current_replicas=metrics.current_replicas,
                target_replicas=metrics.current_replicas,
                reason="Error rate too high to scale down",
                metrics=metrics,
                confidence=0.0
            )
        
        # Calculate target replicas
        target_replicas = max(
            metrics.current_replicas - policy.scale_down_increment,
            policy.min_replicas
        )
        
        reason = f"Scale down triggered by: {', '.join([s[0] for s in signals])}"
        
        return ScalingDecision(
            direction=ScalingDirection.DOWN,
            current_replicas=metrics.current_replicas,
            target_replicas=target_replicas,
            reason=reason,
            metrics=metrics,
            confidence=confidence
        )
    
    def execute_scaling(
        self,
        service_name: str,
        decision: ScalingDecision
    ) -> bool:
        """
        Execute the scaling decision.
        
        Args:
            service_name: Name of the service
            decision: Scaling decision to execute
            
        Returns:
            True if scaling was successful
        """
        if decision.direction == ScalingDirection.NONE:
            return True
        
        # Log the scaling decision
        logger.info(
            f"Executing scaling for {service_name}: "
            f"{decision.current_replicas} -> {decision.target_replicas} "
            f"({decision.reason})"
        )
        
        # Update metrics
        scaling_events_gauge.labels(
            service=service_name,
            direction=decision.direction.value
        ).inc()
        
        # Execute based on environment
        if self.kubernetes_client:
            return self._execute_kubernetes_scaling(
                service_name, decision.target_replicas
            )
        else:
            # For non-Kubernetes environments (e.g., Cloud Run)
            return self._execute_cloud_scaling(
                service_name, decision.target_replicas
            )
    
    def _execute_kubernetes_scaling(
        self,
        service_name: str,
        target_replicas: int
    ) -> bool:
        """Execute scaling in Kubernetes."""
        try:
            # Get deployment name from service name
            deployment_name = f"{service_name}-deployment"
            namespace = getattr(settings, 'KUBERNETES_NAMESPACE', 'default')
            
            # Get current deployment
            deployment = self.kubernetes_client.read_namespaced_deployment(
                name=deployment_name,
                namespace=namespace
            )
            
            # Update replica count
            deployment.spec.replicas = target_replicas
            
            # Apply the change
            self.kubernetes_client.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=deployment
            )
            
            # Update tracking
            self._record_scaling_event(
                service_name,
                deployment.spec.replicas,
                target_replicas
            )
            
            # Update Prometheus metric
            current_replicas_gauge.labels(
                service=service_name,
                deployment=deployment_name
            ).set(target_replicas)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to scale {service_name}: {e}")
            return False
    
    def _execute_cloud_scaling(
        self,
        service_name: str,
        target_replicas: int
    ) -> bool:
        """Execute scaling in cloud environments (e.g., Cloud Run)."""
        # This would integrate with cloud provider APIs
        # For now, just log the intent
        logger.info(
            f"Would scale {service_name} to {target_replicas} replicas "
            "(cloud scaling not implemented)"
        )
        
        # Update tracking
        self._record_scaling_event(
            service_name,
            1,  # Assume current is 1 for serverless
            target_replicas
        )
        
        return True
    
    def _store_metrics(self, service_name: str, metrics: ScalingMetrics) -> None:
        """Store metrics in history for trend analysis."""
        if service_name not in self.metrics_history:
            self.metrics_history[service_name] = []
        
        # Keep last hour of metrics
        cutoff_time = datetime.now() - timedelta(hours=1)
        self.metrics_history[service_name] = [
            m for m in self.metrics_history[service_name]
            if m.timestamp > cutoff_time
        ]
        
        self.metrics_history[service_name].append(metrics)
    
    def _is_in_cooldown(self, service_name: str) -> bool:
        """Check if service is in cooldown period."""
        if service_name not in self.scaling_history:
            return False
        
        policy = self.policies[service_name]
        last_scaling = self.scaling_history[service_name]
        
        if last_scaling['direction'] == 'up':
            cooldown = policy.scale_up_cooldown
        else:
            cooldown = policy.scale_down_cooldown
        
        return datetime.now() - last_scaling['timestamp'] < cooldown
    
    def _is_trend_stable(
        self,
        service_name: str,
        direction: str,
        window_minutes: int = 5
    ) -> bool:
        """Check if the scaling trend is stable."""
        if service_name not in self.metrics_history:
            return False
        
        policy = self.policies[service_name]
        cutoff_time = datetime.now() - timedelta(minutes=window_minutes)
        
        recent_metrics = [
            m for m in self.metrics_history[service_name]
            if m.timestamp > cutoff_time
        ]
        
        if len(recent_metrics) < 3:
            return False
        
        # Count how many data points breach thresholds
        breach_count = 0
        
        for metric in recent_metrics:
            if direction == 'up':
                if (metric.cpu_usage > policy.cpu_scale_up_threshold or
                    metric.memory_usage > policy.memory_scale_up_threshold or
                    metric.response_time_p95 > policy.response_time_scale_up_threshold):
                    breach_count += 1
            else:
                if (metric.cpu_usage < policy.cpu_scale_down_threshold and
                    metric.memory_usage < policy.memory_scale_down_threshold and
                    metric.response_time_p95 < policy.response_time_scale_down_threshold):
                    breach_count += 1
        
        breach_percentage = (breach_count / len(recent_metrics)) * 100
        return breach_percentage >= policy.required_breach_percentage
    
    def _predict_future_load(self, service_name: str) -> float:
        """
        Predict future load multiplier using simple trend analysis.
        
        Returns:
            Predicted load multiplier (1.0 = no change, 2.0 = double load)
        """
        if service_name not in self.metrics_history:
            return 1.0
        
        # Get last 30 minutes of data
        cutoff_time = datetime.now() - timedelta(minutes=30)
        recent_metrics = [
            m for m in self.metrics_history[service_name]
            if m.timestamp > cutoff_time
        ]
        
        if len(recent_metrics) < 10:
            return 1.0
        
        # Simple linear regression on request rate
        timestamps = [(m.timestamp - recent_metrics[0].timestamp).total_seconds() 
                     for m in recent_metrics]
        request_rates = [m.request_rate for m in recent_metrics]
        
        if not request_rates or max(request_rates) == 0:
            return 1.0
        
        # Calculate trend
        n = len(timestamps)
        sum_x = sum(timestamps)
        sum_y = sum(request_rates)
        sum_xy = sum(x * y for x, y in zip(timestamps, request_rates))
        sum_x2 = sum(x * x for x in timestamps)
        
        # Slope calculation
        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0:
            return 1.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        
        # Predict 10 minutes into future
        future_seconds = 600
        current_rate = request_rates[-1]
        predicted_rate = current_rate + (slope * future_seconds)
        
        # Return multiplier, capped at reasonable values
        multiplier = predicted_rate / current_rate if current_rate > 0 else 1.0
        return max(0.5, min(3.0, multiplier))
    
    def _record_scaling_event(
        self,
        service_name: str,
        from_replicas: int,
        to_replicas: int
    ) -> None:
        """Record scaling event in history."""
        self.scaling_history[service_name] = {
            'timestamp': datetime.now(),
            'from_replicas': from_replicas,
            'to_replicas': to_replicas,
            'direction': 'up' if to_replicas > from_replicas else 'down'
        }
        
        # Also store in cache for persistence
        cache.set(
            f"scaling_history:{service_name}",
            self.scaling_history[service_name],
            timeout=86400  # 24 hours
        )
    
    def get_scaling_recommendations(self) -> Dict[str, Any]:
        """
        Get scaling recommendations for all services.
        
        Returns:
            Dictionary of recommendations by service
        """
        recommendations = {}
        
        for service_name, policy in self.policies.items():
            # Get latest metrics (would come from monitoring system)
            latest_metrics = self._get_latest_metrics(service_name)
            if not latest_metrics:
                continue
            
            # Evaluate scaling
            decision = self.evaluate_scaling(service_name, latest_metrics)
            
            recommendations[service_name] = {
                'current_replicas': decision.current_replicas,
                'recommended_replicas': decision.target_replicas,
                'direction': decision.direction.value,
                'reason': decision.reason,
                'confidence': decision.confidence,
                'metrics': {
                    'cpu_usage': latest_metrics.cpu_usage,
                    'memory_usage': latest_metrics.memory_usage,
                    'response_time_p95': latest_metrics.response_time_p95,
                    'request_rate': latest_metrics.request_rate,
                    'error_rate': latest_metrics.error_rate
                },
                'policy': {
                    'min_replicas': policy.min_replicas,
                    'max_replicas': policy.max_replicas,
                    'cpu_threshold': policy.cpu_scale_up_threshold,
                    'response_time_threshold': policy.response_time_scale_up_threshold
                }
            }
        
        return recommendations
    
    def _get_latest_metrics(self, service_name: str) -> Optional[ScalingMetrics]:
        """Get latest metrics for a service."""
        # In production, this would query Prometheus or monitoring system
        # For now, return sample data
        import random
        
        return ScalingMetrics(
            timestamp=datetime.now(),
            cpu_usage=random.uniform(20, 80),
            memory_usage=random.uniform(30, 70),
            response_time_p95=random.uniform(0.5, 3.0),
            request_rate=random.uniform(50, 200),
            current_replicas=3,
            error_rate=random.uniform(0, 2)
        )