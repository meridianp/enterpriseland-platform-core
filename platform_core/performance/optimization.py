"""
Performance Optimization Tools

Query optimization, cache warming, and performance tuning utilities.
"""

import logging
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from django.db import connection, models
from django.db.models import Prefetch, Q, F
from django.core.cache import cache
from django.conf import settings
import hashlib
import json

logger = logging.getLogger(__name__)


class QueryOptimizer:
    """
    Optimize database queries for better performance.
    """
    
    def __init__(self):
        self.optimization_cache = {}
        self.index_suggestions = []
    
    def optimize_queryset(self, queryset: models.QuerySet) -> models.QuerySet:
        """
        Optimize a queryset with appropriate select_related and prefetch_related.
        """
        model = queryset.model
        
        # Get optimization hints from cache
        cache_key = f"query_optimization:{model._meta.label}"
        optimizations = cache.get(cache_key)
        
        if not optimizations:
            optimizations = self._analyze_model_relationships(model)
            cache.set(cache_key, optimizations, timeout=3600)
        
        # Apply select_related for foreign keys
        if optimizations['select_related']:
            queryset = queryset.select_related(*optimizations['select_related'])
        
        # Apply prefetch_related for reverse foreign keys and many-to-many
        if optimizations['prefetch_related']:
            queryset = queryset.prefetch_related(*optimizations['prefetch_related'])
        
        # Apply only() for field limiting if specified
        if optimizations.get('only_fields'):
            queryset = queryset.only(*optimizations['only_fields'])
        
        return queryset
    
    def analyze_slow_queries(self, threshold_ms: int = 100) -> List[Dict[str, Any]]:
        """
        Analyze slow queries and provide optimization suggestions.
        """
        slow_queries = []
        
        # Get recent queries from monitoring
        with connection.cursor() as cursor:
            # PostgreSQL specific - get slow queries from pg_stat_statements
            try:
                cursor.execute("""
                    SELECT 
                        query,
                        mean_exec_time,
                        calls,
                        total_exec_time
                    FROM pg_stat_statements
                    WHERE mean_exec_time > %s
                    ORDER BY mean_exec_time DESC
                    LIMIT 20
                """, [threshold_ms])
                
                for row in cursor.fetchall():
                    query_info = {
                        'query': row[0],
                        'avg_time': row[1],
                        'calls': row[2],
                        'total_time': row[3],
                        'suggestions': self._generate_query_suggestions(row[0])
                    }
                    slow_queries.append(query_info)
                    
            except Exception as e:
                logger.warning(f"Could not analyze slow queries: {e}")
        
        return slow_queries
    
    def suggest_indexes(self, model: models.Model) -> List[Dict[str, Any]]:
        """
        Suggest database indexes based on query patterns.
        """
        suggestions = []
        meta = model._meta
        
        # Analyze foreign key fields without indexes
        for field in meta.get_fields():
            if isinstance(field, models.ForeignKey):
                if not field.db_index:
                    suggestions.append({
                        'model': meta.label,
                        'field': field.name,
                        'type': 'foreign_key',
                        'sql': f"CREATE INDEX idx_{meta.db_table}_{field.name} "
                               f"ON {meta.db_table} ({field.column});"
                    })
            
            # Check for commonly filtered fields
            if hasattr(field, 'db_index') and not field.db_index:
                if field.name in ['status', 'created_date', 'is_active']:
                    suggestions.append({
                        'model': meta.label,
                        'field': field.name,
                        'type': 'filter_field',
                        'sql': f"CREATE INDEX idx_{meta.db_table}_{field.name} "
                               f"ON {meta.db_table} ({field.column});"
                    })
        
        # Suggest composite indexes for common filter combinations
        common_filters = self._get_common_filter_combinations(model)
        for fields in common_filters:
            columns = [meta.get_field(f).column for f in fields]
            suggestions.append({
                'model': meta.label,
                'fields': fields,
                'type': 'composite',
                'sql': f"CREATE INDEX idx_{meta.db_table}_{'_'.join(fields)} "
                       f"ON {meta.db_table} ({', '.join(columns)});"
            })
        
        return suggestions
    
    def _analyze_model_relationships(self, model: models.Model) -> Dict[str, Any]:
        """
        Analyze model relationships for optimization.
        """
        optimizations = {
            'select_related': [],
            'prefetch_related': [],
            'only_fields': []
        }
        
        meta = model._meta
        
        # Analyze foreign keys for select_related
        for field in meta.get_fields():
            if isinstance(field, models.ForeignKey):
                # Add to select_related if commonly accessed
                if self._is_commonly_accessed(model, field.name):
                    optimizations['select_related'].append(field.name)
            
            # Analyze reverse foreign keys and many-to-many
            elif field.is_relation and not field.concrete:
                if self._is_commonly_accessed(model, field.name):
                    optimizations['prefetch_related'].append(field.name)
        
        return optimizations
    
    def _is_commonly_accessed(self, model: models.Model, field_name: str) -> bool:
        """
        Determine if a field is commonly accessed based on query patterns.
        """
        # In a real implementation, this would analyze actual query logs
        # For now, use heuristics
        common_fields = [
            'user', 'group', 'created_by', 'modified_by',
            'parent', 'category', 'tags', 'permissions'
        ]
        
        return field_name in common_fields
    
    def _generate_query_suggestions(self, query: str) -> List[str]:
        """
        Generate optimization suggestions for a specific query.
        """
        suggestions = []
        query_lower = query.lower()
        
        # Check for missing indexes
        if 'where' in query_lower and 'index' not in query_lower:
            suggestions.append("Consider adding an index on WHERE clause columns")
        
        # Check for SELECT *
        if 'select *' in query_lower:
            suggestions.append("Use specific column names instead of SELECT *")
        
        # Check for missing LIMIT
        if 'limit' not in query_lower and 'select' in query_lower:
            suggestions.append("Consider adding LIMIT clause to reduce result set")
        
        # Check for NOT IN
        if 'not in' in query_lower:
            suggestions.append("Consider using NOT EXISTS instead of NOT IN")
        
        # Check for OR conditions
        if ' or ' in query_lower:
            suggestions.append("OR conditions can prevent index usage, consider using UNION")
        
        return suggestions
    
    def _get_common_filter_combinations(self, model: models.Model) -> List[List[str]]:
        """
        Get common filter combinations for composite indexes.
        """
        # In production, analyze actual query patterns
        # For now, return common patterns
        common_patterns = [
            ['status', 'created_date'],
            ['is_active', 'created_date'],
            ['group', 'status'],
            ['user', 'is_active']
        ]
        
        # Filter to only fields that exist on the model
        meta = model._meta
        field_names = {f.name for f in meta.get_fields()}
        
        return [
            pattern for pattern in common_patterns
            if all(field in field_names for field in pattern)
        ]


class CacheWarmer:
    """
    Warm up caches for better performance.
    """
    
    def __init__(self):
        self.warming_strategies = {}
        self.warming_schedule = {}
    
    def register_warming_strategy(self, key_pattern: str, 
                                strategy: callable) -> None:
        """
        Register a cache warming strategy.
        """
        self.warming_strategies[key_pattern] = strategy
    
    def warm_cache(self, pattern: Optional[str] = None) -> Dict[str, Any]:
        """
        Warm caches based on registered strategies.
        """
        results = {
            'warmed_keys': 0,
            'failed_keys': 0,
            'duration': 0,
            'details': []
        }
        
        start_time = datetime.now()
        
        patterns = [pattern] if pattern else self.warming_strategies.keys()
        
        for key_pattern in patterns:
            if key_pattern not in self.warming_strategies:
                continue
            
            strategy = self.warming_strategies[key_pattern]
            
            try:
                # Execute warming strategy
                warmed = strategy()
                
                results['warmed_keys'] += len(warmed)
                results['details'].append({
                    'pattern': key_pattern,
                    'keys_warmed': len(warmed),
                    'status': 'success'
                })
                
            except Exception as e:
                logger.error(f"Cache warming failed for {key_pattern}: {e}")
                results['failed_keys'] += 1
                results['details'].append({
                    'pattern': key_pattern,
                    'status': 'failed',
                    'error': str(e)
                })
        
        results['duration'] = (datetime.now() - start_time).total_seconds()
        
        # Store warming results
        cache.set('cache_warming:last_run', results, timeout=3600)
        
        return results
    
    def warm_queryset_cache(self, model: models.Model, 
                          filters: Optional[Dict] = None) -> List[str]:
        """
        Warm cache for common queryset patterns.
        """
        warmed_keys = []
        
        # Common filter combinations
        filter_combinations = [
            {},  # All objects
            {'is_active': True} if hasattr(model, 'is_active') else {},
            {'status': 'active'} if hasattr(model, 'status') else {},
        ]
        
        if filters:
            filter_combinations.append(filters)
        
        for filter_set in filter_combinations:
            if not all(hasattr(model, k) for k in filter_set.keys()):
                continue
            
            # Generate cache key
            cache_key = self._generate_cache_key(model, filter_set)
            
            # Execute query and cache
            queryset = model.objects.filter(**filter_set)
            
            # Optimize queryset
            optimizer = QueryOptimizer()
            queryset = optimizer.optimize_queryset(queryset)
            
            # Cache the results
            results = list(queryset[:100])  # Limit to prevent memory issues
            cache.set(cache_key, results, timeout=3600)
            
            warmed_keys.append(cache_key)
        
        return warmed_keys
    
    def warm_aggregation_cache(self, model: models.Model) -> List[str]:
        """
        Warm cache for common aggregations.
        """
        warmed_keys = []
        
        # Common aggregations
        aggregations = [
            'count',
            'sum',
            'avg',
            'min',
            'max'
        ]
        
        # Common group by fields
        group_fields = []
        for field in model._meta.get_fields():
            if field.name in ['status', 'category', 'type', 'created_date__date']:
                group_fields.append(field.name)
        
        for agg_type in aggregations:
            for group_field in group_fields:
                cache_key = f"aggregation:{model._meta.label}:{group_field}:{agg_type}"
                
                # Perform aggregation
                try:
                    if agg_type == 'count':
                        result = model.objects.values(group_field).annotate(
                            value=models.Count('id')
                        )
                    else:
                        # Skip other aggregations for non-numeric fields
                        continue
                    
                    # Cache the result
                    cache.set(cache_key, list(result), timeout=3600)
                    warmed_keys.append(cache_key)
                    
                except Exception as e:
                    logger.warning(f"Could not warm aggregation cache: {e}")
        
        return warmed_keys
    
    def _generate_cache_key(self, model: models.Model, 
                          filters: Dict[str, Any]) -> str:
        """
        Generate consistent cache key for queryset.
        """
        # Sort filters for consistent keys
        sorted_filters = sorted(filters.items())
        filter_string = json.dumps(sorted_filters)
        
        # Create hash of filter string
        filter_hash = hashlib.md5(filter_string.encode()).hexdigest()[:8]
        
        return f"queryset:{model._meta.label}:{filter_hash}"


class PerformanceOptimizer:
    """
    High-level performance optimization coordinator.
    """
    
    def __init__(self):
        self.query_optimizer = QueryOptimizer()
        self.cache_warmer = CacheWarmer()
        self.optimization_history = []
    
    def run_optimization_suite(self) -> Dict[str, Any]:
        """
        Run complete optimization suite.
        """
        results = {
            'timestamp': datetime.now().isoformat(),
            'optimizations': {},
            'improvements': [],
            'recommendations': []
        }
        
        # 1. Analyze slow queries
        logger.info("Analyzing slow queries...")
        slow_queries = self.query_optimizer.analyze_slow_queries()
        results['optimizations']['slow_queries'] = {
            'count': len(slow_queries),
            'queries': slow_queries[:10]  # Top 10
        }
        
        # 2. Generate index suggestions
        logger.info("Generating index suggestions...")
        from django.apps import apps
        
        all_suggestions = []
        for model in apps.get_models():
            suggestions = self.query_optimizer.suggest_indexes(model)
            all_suggestions.extend(suggestions)
        
        results['optimizations']['index_suggestions'] = {
            'count': len(all_suggestions),
            'suggestions': all_suggestions[:20]  # Top 20
        }
        
        # 3. Warm caches
        logger.info("Warming caches...")
        cache_results = self.cache_warmer.warm_cache()
        results['optimizations']['cache_warming'] = cache_results
        
        # 4. Analyze query patterns
        logger.info("Analyzing query patterns...")
        patterns = self._analyze_query_patterns()
        results['optimizations']['query_patterns'] = patterns
        
        # 5. Generate recommendations
        results['recommendations'] = self._generate_recommendations(results)
        
        # Store optimization history
        self.optimization_history.append(results)
        cache.set('optimization:last_run', results, timeout=86400)
        
        return results
    
    def optimize_model_queries(self, model: models.Model) -> Dict[str, Any]:
        """
        Optimize queries for a specific model.
        """
        results = {
            'model': model._meta.label,
            'optimizations': []
        }
        
        # Get common querysets
        common_queries = self._get_common_queries(model)
        
        for query_desc, queryset in common_queries.items():
            # Measure original performance
            start_time = datetime.now()
            list(queryset[:100])
            original_time = (datetime.now() - start_time).total_seconds()
            
            # Optimize
            optimized = self.query_optimizer.optimize_queryset(queryset)
            
            # Measure optimized performance
            start_time = datetime.now()
            list(optimized[:100])
            optimized_time = (datetime.now() - start_time).total_seconds()
            
            improvement = ((original_time - optimized_time) / original_time) * 100
            
            results['optimizations'].append({
                'query': query_desc,
                'original_time': original_time,
                'optimized_time': optimized_time,
                'improvement_percent': improvement
            })
        
        return results
    
    def _analyze_query_patterns(self) -> Dict[str, Any]:
        """
        Analyze common query patterns for optimization.
        """
        patterns = {
            'n_plus_one': [],
            'missing_indexes': [],
            'inefficient_filters': [],
            'large_result_sets': []
        }
        
        # Analyze recent queries
        # In production, this would analyze actual query logs
        
        return patterns
    
    def _get_common_queries(self, model: models.Model) -> Dict[str, models.QuerySet]:
        """
        Get common query patterns for a model.
        """
        queries = {
            'all': model.objects.all(),
            'recent': model.objects.all().order_by('-id')[:100]
        }
        
        # Add status-based queries if applicable
        if hasattr(model, 'status'):
            queries['active'] = model.objects.filter(status='active')
        
        # Add date-based queries if applicable
        if hasattr(model, 'created_date'):
            last_week = datetime.now() - timedelta(days=7)
            queries['recent_created'] = model.objects.filter(
                created_date__gte=last_week
            )
        
        return queries
    
    def _generate_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """
        Generate optimization recommendations based on analysis.
        """
        recommendations = []
        
        # Check slow queries
        slow_count = results['optimizations']['slow_queries']['count']
        if slow_count > 10:
            recommendations.append(
                f"Found {slow_count} slow queries. "
                "Priority: Optimize the top 5 slowest queries first."
            )
        
        # Check index suggestions
        index_count = results['optimizations']['index_suggestions']['count']
        if index_count > 0:
            recommendations.append(
                f"Found {index_count} missing indexes. "
                "Adding these indexes could significantly improve performance."
            )
        
        # Check cache warming
        cache_results = results['optimizations']['cache_warming']
        if cache_results['failed_keys'] > 0:
            recommendations.append(
                f"Cache warming failed for {cache_results['failed_keys']} keys. "
                "Review cache warming strategies."
            )
        
        # Add general recommendations
        recommendations.extend([
            "Enable query result caching for frequently accessed data",
            "Consider implementing database connection pooling",
            "Review and optimize N+1 query patterns",
            "Implement pagination for large result sets"
        ])
        
        return recommendations


# Create global optimizer instance
performance_optimizer = PerformanceOptimizer()