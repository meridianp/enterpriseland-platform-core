"""
Database Query Optimization

Tools for optimizing database queries, indexes, and connections.
"""

import logging
import time
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
from django.db import connection, connections, models
from django.db.models import Q, F, Count, Sum, Avg
from django.conf import settings
from django.core.cache import cache
import psycopg2.extras
import json

logger = logging.getLogger(__name__)


class QueryPlanAnalyzer:
    """
    Analyze query execution plans for optimization opportunities.
    """
    
    def __init__(self, connection_alias='default'):
        self.connection = connections[connection_alias]
        self.problematic_patterns = []
    
    def analyze_query(self, query: str, params: Optional[List] = None) -> Dict[str, Any]:
        """
        Analyze a single query's execution plan.
        """
        with self.connection.cursor() as cursor:
            # Get execution plan
            explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
            
            try:
                if params:
                    cursor.execute(explain_query, params)
                else:
                    cursor.execute(explain_query)
                
                plan = cursor.fetchone()[0][0]
                
                # Analyze plan
                analysis = self._analyze_plan(plan)
                
                return {
                    'query': query,
                    'execution_time': plan.get('Execution Time', 0),
                    'planning_time': plan.get('Planning Time', 0),
                    'total_cost': plan['Plan'].get('Total Cost', 0),
                    'issues': analysis['issues'],
                    'suggestions': analysis['suggestions'],
                    'plan_details': plan
                }
                
            except Exception as e:
                logger.error(f"Error analyzing query: {e}")
                return {
                    'query': query,
                    'error': str(e)
                }
    
    def _analyze_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze execution plan for issues and suggestions.
        """
        issues = []
        suggestions = []
        
        # Check for sequential scans on large tables
        seq_scans = self._find_sequential_scans(plan['Plan'])
        for scan in seq_scans:
            if scan['rows'] > 1000:
                issues.append(f"Sequential scan on large table: {scan['table']}")
                suggestions.append(f"Consider adding index on {scan['table']}")
        
        # Check for nested loops with high cost
        nested_loops = self._find_nested_loops(plan['Plan'])
        for loop in nested_loops:
            if loop['total_cost'] > 1000:
                issues.append("High-cost nested loop join detected")
                suggestions.append("Consider using hash join or merge join")
        
        # Check for missing indexes
        if 'Index Scan' not in str(plan) and plan['Plan'].get('Total Cost', 0) > 100:
            issues.append("No index scans found in query plan")
            suggestions.append("Review query conditions and add appropriate indexes")
        
        # Check for sorting operations
        sorts = self._find_sorts(plan['Plan'])
        for sort in sorts:
            if sort['cost'] > 500:
                issues.append(f"Expensive sort operation: {sort['cost']}")
                suggestions.append("Consider adding index for ORDER BY columns")
        
        return {
            'issues': issues,
            'suggestions': suggestions
        }
    
    def _find_sequential_scans(self, node: Dict[str, Any], 
                             scans: Optional[List] = None) -> List[Dict[str, Any]]:
        """Find all sequential scans in plan."""
        if scans is None:
            scans = []
        
        if node.get('Node Type') == 'Seq Scan':
            scans.append({
                'table': node.get('Relation Name', 'unknown'),
                'rows': node.get('Actual Rows', 0),
                'cost': node.get('Total Cost', 0)
            })
        
        # Recurse through child nodes
        for child in node.get('Plans', []):
            self._find_sequential_scans(child, scans)
        
        return scans
    
    def _find_nested_loops(self, node: Dict[str, Any], 
                          loops: Optional[List] = None) -> List[Dict[str, Any]]:
        """Find all nested loop joins in plan."""
        if loops is None:
            loops = []
        
        if node.get('Node Type') == 'Nested Loop':
            loops.append({
                'total_cost': node.get('Total Cost', 0),
                'rows': node.get('Actual Rows', 0)
            })
        
        for child in node.get('Plans', []):
            self._find_nested_loops(child, loops)
        
        return loops
    
    def _find_sorts(self, node: Dict[str, Any], 
                   sorts: Optional[List] = None) -> List[Dict[str, Any]]:
        """Find all sort operations in plan."""
        if sorts is None:
            sorts = []
        
        if node.get('Node Type') == 'Sort':
            sorts.append({
                'cost': node.get('Total Cost', 0),
                'method': node.get('Sort Method', 'unknown')
            })
        
        for child in node.get('Plans', []):
            self._find_sorts(child, sorts)
        
        return sorts


class IndexAnalyzer:
    """
    Analyze and suggest database indexes.
    """
    
    def __init__(self, connection_alias='default'):
        self.connection = connections[connection_alias]
        self.index_candidates = defaultdict(list)
    
    def analyze_missing_indexes(self) -> List[Dict[str, Any]]:
        """
        Analyze database for missing indexes.
        """
        suggestions = []
        
        # Get table statistics
        with self.connection.cursor() as cursor:
            # Find tables with sequential scans
            cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    seq_scan,
                    seq_tup_read,
                    idx_scan,
                    idx_tup_fetch,
                    n_tup_ins + n_tup_upd + n_tup_del as write_activity
                FROM pg_stat_user_tables
                WHERE seq_scan > 0
                ORDER BY seq_tup_read DESC
                LIMIT 20
            """)
            
            for row in cursor.fetchall():
                schema, table, seq_scans, seq_reads = row[:4]
                idx_scans, idx_reads, writes = row[4:]
                
                # High sequential scan ratio indicates missing index
                if seq_scans > 0 and (idx_scans == 0 or seq_reads / seq_scans > 1000):
                    suggestions.append({
                        'table': f"{schema}.{table}",
                        'issue': 'High sequential scan activity',
                        'seq_scans': seq_scans,
                        'seq_reads': seq_reads,
                        'recommendation': 'Analyze query patterns and add appropriate indexes'
                    })
        
        # Analyze foreign key columns without indexes
        suggestions.extend(self._check_foreign_key_indexes())
        
        # Analyze frequently filtered columns
        suggestions.extend(self._analyze_filter_columns())
        
        return suggestions
    
    def suggest_composite_indexes(self, model: models.Model) -> List[Dict[str, Any]]:
        """
        Suggest composite indexes based on query patterns.
        """
        suggestions = []
        table_name = model._meta.db_table
        
        # Analyze recent queries for this table
        with self.connection.cursor() as cursor:
            # Get column usage statistics
            cursor.execute("""
                SELECT 
                    attname,
                    n_distinct,
                    null_frac,
                    avg_width
                FROM pg_stats
                WHERE tablename = %s
                AND n_distinct > 1
                ORDER BY n_distinct DESC
            """, [table_name])
            
            column_stats = {
                row[0]: {
                    'n_distinct': row[1],
                    'null_frac': row[2],
                    'avg_width': row[3]
                }
                for row in cursor.fetchall()
            }
        
        # Common composite index patterns
        patterns = [
            # Status + Date for filtering active records by date
            ['status', 'created_date'],
            ['is_active', 'created_date'],
            # Foreign key + Status for filtered relationships
            ['user_id', 'status'],
            ['group_id', 'is_active'],
            # Sorting patterns
            ['created_date', 'id'],
            ['updated_date', 'id']
        ]
        
        for pattern in patterns:
            # Check if all columns exist
            if all(model._meta.get_field(col) for col in pattern):
                # Calculate index benefit
                benefit = self._calculate_index_benefit(
                    table_name, pattern, column_stats
                )
                
                if benefit > 0.5:  # Threshold for recommendation
                    suggestions.append({
                        'table': table_name,
                        'columns': pattern,
                        'type': 'composite',
                        'benefit_score': benefit,
                        'sql': self._generate_index_sql(table_name, pattern)
                    })
        
        return suggestions
    
    def analyze_index_usage(self) -> Dict[str, Any]:
        """
        Analyze current index usage and identify unused indexes.
        """
        usage_stats = {
            'total_indexes': 0,
            'unused_indexes': [],
            'inefficient_indexes': [],
            'duplicate_indexes': []
        }
        
        with self.connection.cursor() as cursor:
            # Get index usage statistics
            cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    indexname,
                    idx_scan,
                    idx_tup_read,
                    idx_tup_fetch,
                    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
                FROM pg_stat_user_indexes
                JOIN pg_index ON pg_index.indexrelid = pg_stat_user_indexes.indexrelid
                WHERE NOT indisprimary
                ORDER BY idx_scan
            """)
            
            for row in cursor.fetchall():
                schema, table, index, scans = row[:4]
                reads, fetches, size = row[4:]
                
                usage_stats['total_indexes'] += 1
                
                # Identify unused indexes
                if scans == 0:
                    usage_stats['unused_indexes'].append({
                        'index': f"{schema}.{index}",
                        'table': f"{schema}.{table}",
                        'size': size,
                        'recommendation': 'Consider dropping this unused index'
                    })
                
                # Identify inefficient indexes
                elif scans > 0 and reads > 0 and fetches / reads < 0.01:
                    usage_stats['inefficient_indexes'].append({
                        'index': f"{schema}.{index}",
                        'table': f"{schema}.{table}",
                        'efficiency': fetches / reads,
                        'recommendation': 'Index may need rebuilding or redesign'
                    })
        
        # Check for duplicate indexes
        usage_stats['duplicate_indexes'] = self._find_duplicate_indexes()
        
        return usage_stats
    
    def _check_foreign_key_indexes(self) -> List[Dict[str, Any]]:
        """Check for foreign keys without indexes."""
        suggestions = []
        
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    tc.table_schema,
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND NOT EXISTS (
                    SELECT 1
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid
                    WHERE a.attname = kcu.column_name
                    AND i.indrelid = (tc.table_schema || '.' || tc.table_name)::regclass
                )
            """)
            
            for row in cursor.fetchall():
                schema, table, column, foreign_table = row
                suggestions.append({
                    'table': f"{schema}.{table}",
                    'column': column,
                    'issue': 'Foreign key without index',
                    'foreign_table': foreign_table,
                    'sql': f"CREATE INDEX idx_{table}_{column} ON {schema}.{table} ({column});"
                })
        
        return suggestions
    
    def _analyze_filter_columns(self) -> List[Dict[str, Any]]:
        """Analyze frequently filtered columns that need indexes."""
        suggestions = []
        
        # Common filter columns that should be indexed
        common_filters = [
            'status', 'is_active', 'created_date', 'updated_date',
            'deleted_at', 'user_id', 'group_id', 'type', 'category'
        ]
        
        # This would analyze actual query logs in production
        # For now, check if common columns exist without indexes
        
        return suggestions
    
    def _calculate_index_benefit(self, table: str, columns: List[str], 
                               stats: Dict[str, Any]) -> float:
        """Calculate benefit score for potential index."""
        benefit = 0.0
        
        for col in columns:
            if col in stats:
                col_stats = stats[col]
                
                # High cardinality is good for indexes
                if col_stats['n_distinct'] > 100:
                    benefit += 0.3
                elif col_stats['n_distinct'] > 10:
                    benefit += 0.2
                
                # Low null fraction is good
                if col_stats['null_frac'] < 0.1:
                    benefit += 0.2
                
                # Small column width is good
                if col_stats['avg_width'] < 20:
                    benefit += 0.1
        
        return benefit / len(columns)
    
    def _generate_index_sql(self, table: str, columns: List[str]) -> str:
        """Generate SQL for creating index."""
        index_name = f"idx_{table}_{'_'.join(columns)}"
        column_list = ', '.join(columns)
        return f"CREATE INDEX {index_name} ON {table} ({column_list});"
    
    def _find_duplicate_indexes(self) -> List[Dict[str, Any]]:
        """Find duplicate or redundant indexes."""
        duplicates = []
        
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    idx1.indexname AS index1,
                    idx2.indexname AS index2,
                    idx1.tablename,
                    pg_get_indexdef(idx1.indexrelid) AS def1,
                    pg_get_indexdef(idx2.indexrelid) AS def2
                FROM pg_stat_user_indexes idx1
                JOIN pg_stat_user_indexes idx2 
                    ON idx1.tablename = idx2.tablename
                    AND idx1.indexname < idx2.indexname
                WHERE pg_get_indexdef(idx1.indexrelid) LIKE '%' || 
                      pg_get_indexdef(idx2.indexrelid) || '%'
            """)
            
            for row in cursor.fetchall():
                duplicates.append({
                    'index1': row[0],
                    'index2': row[1],
                    'table': row[2],
                    'recommendation': f"Consider dropping {row[1]} as it may be redundant"
                })
        
        return duplicates


class DatabaseOptimizer:
    """
    Comprehensive database optimization coordinator.
    """
    
    def __init__(self, connection_alias='default'):
        self.connection_alias = connection_alias
        self.query_analyzer = QueryPlanAnalyzer(connection_alias)
        self.index_analyzer = IndexAnalyzer(connection_alias)
        self.optimization_history = []
    
    def run_optimization_analysis(self) -> Dict[str, Any]:
        """
        Run comprehensive database optimization analysis.
        """
        logger.info("Starting database optimization analysis...")
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'connection': self.connection_alias,
            'optimizations': {}
        }
        
        # 1. Analyze slow queries
        logger.info("Analyzing slow queries...")
        results['optimizations']['slow_queries'] = self._analyze_slow_queries()
        
        # 2. Analyze missing indexes
        logger.info("Analyzing missing indexes...")
        results['optimizations']['missing_indexes'] = (
            self.index_analyzer.analyze_missing_indexes()
        )
        
        # 3. Analyze index usage
        logger.info("Analyzing index usage...")
        results['optimizations']['index_usage'] = (
            self.index_analyzer.analyze_index_usage()
        )
        
        # 4. Analyze table statistics
        logger.info("Analyzing table statistics...")
        results['optimizations']['table_stats'] = self._analyze_table_statistics()
        
        # 5. Generate recommendations
        results['recommendations'] = self._generate_recommendations(results)
        
        # Store history
        self.optimization_history.append(results)
        cache.set(f'db_optimization:{self.connection_alias}:latest', results, 86400)
        
        return results
    
    def optimize_model_queries(self, model: models.Model) -> Dict[str, Any]:
        """
        Optimize queries for a specific model.
        """
        results = {
            'model': model._meta.label,
            'table': model._meta.db_table,
            'optimizations': []
        }
        
        # Get common query patterns
        patterns = self._get_model_query_patterns(model)
        
        for pattern_name, queryset in patterns.items():
            # Convert to SQL
            sql, params = queryset.query.get_compiler('default').as_sql()
            
            # Analyze query plan
            analysis = self.query_analyzer.analyze_query(sql, params)
            
            if analysis.get('issues'):
                results['optimizations'].append({
                    'pattern': pattern_name,
                    'issues': analysis['issues'],
                    'suggestions': analysis['suggestions'],
                    'execution_time': analysis.get('execution_time', 0)
                })
        
        # Suggest indexes for this model
        index_suggestions = self.index_analyzer.suggest_composite_indexes(model)
        if index_suggestions:
            results['index_suggestions'] = index_suggestions
        
        return results
    
    def _analyze_slow_queries(self) -> List[Dict[str, Any]]:
        """Analyze slow queries from pg_stat_statements."""
        slow_queries = []
        
        with connections[self.connection_alias].cursor() as cursor:
            try:
                cursor.execute("""
                    SELECT 
                        query,
                        calls,
                        total_exec_time,
                        mean_exec_time,
                        stddev_exec_time,
                        rows
                    FROM pg_stat_statements
                    WHERE mean_exec_time > 100  -- queries slower than 100ms
                    ORDER BY mean_exec_time DESC
                    LIMIT 20
                """)
                
                for row in cursor.fetchall():
                    query = row[0]
                    
                    # Skip internal queries
                    if any(skip in query.lower() for skip in 
                          ['pg_', 'information_schema', 'commit', 'begin']):
                        continue
                    
                    # Analyze query plan
                    analysis = self.query_analyzer.analyze_query(query)
                    
                    slow_queries.append({
                        'query': query[:200] + '...' if len(query) > 200 else query,
                        'calls': row[1],
                        'avg_time': row[3],
                        'total_time': row[2],
                        'analysis': analysis
                    })
                    
            except Exception as e:
                logger.warning(f"Could not analyze slow queries: {e}")
                logger.info("Ensure pg_stat_statements extension is enabled")
        
        return slow_queries
    
    def _analyze_table_statistics(self) -> Dict[str, Any]:
        """Analyze table statistics and vacuum status."""
        stats = {
            'tables_need_vacuum': [],
            'tables_need_analyze': [],
            'bloated_tables': []
        }
        
        with connections[self.connection_alias].cursor() as cursor:
            # Check for tables needing vacuum/analyze
            cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    n_tup_ins + n_tup_upd + n_tup_del as write_activity,
                    n_dead_tup,
                    last_vacuum,
                    last_autovacuum,
                    last_analyze,
                    last_autoanalyze
                FROM pg_stat_user_tables
                WHERE n_dead_tup > 1000
                OR (
                    last_vacuum IS NULL 
                    AND last_autovacuum IS NULL
                    AND n_tup_ins + n_tup_upd + n_tup_del > 10000
                )
                ORDER BY n_dead_tup DESC
            """)
            
            for row in cursor.fetchall():
                schema, table = row[:2]
                writes, dead_tuples = row[2:4]
                last_vacuum = row[4] or row[5]  # manual or auto
                last_analyze = row[6] or row[7]
                
                if dead_tuples > 10000:
                    stats['tables_need_vacuum'].append({
                        'table': f"{schema}.{table}",
                        'dead_tuples': dead_tuples,
                        'last_vacuum': last_vacuum.isoformat() if last_vacuum else None,
                        'recommendation': 'Run VACUUM to reclaim space'
                    })
                
                if not last_analyze or (
                    datetime.now(last_analyze.tzinfo) - last_analyze > timedelta(days=7)
                ):
                    stats['tables_need_analyze'].append({
                        'table': f"{schema}.{table}",
                        'last_analyze': last_analyze.isoformat() if last_analyze else None,
                        'recommendation': 'Run ANALYZE to update statistics'
                    })
            
            # Check for table bloat
            cursor.execute("""
                SELECT
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                    CASE 
                        WHEN pg_total_relation_size(schemaname||'.'||tablename) > 0
                        THEN (n_dead_tup::float / pg_total_relation_size(schemaname||'.'||tablename)) * 100
                        ELSE 0
                    END AS bloat_ratio
                FROM pg_stat_user_tables
                WHERE pg_total_relation_size(schemaname||'.'||tablename) > 1048576  -- > 1MB
                AND n_dead_tup > 1000
                ORDER BY bloat_ratio DESC
                LIMIT 10
            """)
            
            for row in cursor.fetchall():
                if row[3] > 20:  # More than 20% bloat
                    stats['bloated_tables'].append({
                        'table': f"{row[0]}.{row[1]}",
                        'size': row[2],
                        'bloat_percent': round(row[3], 2),
                        'recommendation': 'Consider VACUUM FULL or pg_repack'
                    })
        
        return stats
    
    def _get_model_query_patterns(self, model: models.Model) -> Dict[str, models.QuerySet]:
        """Get common query patterns for a model."""
        patterns = {
            'all': model.objects.all(),
            'recent': model.objects.all().order_by('-id')[:100]
        }
        
        # Add field-specific patterns
        fields = model._meta.get_fields()
        
        for field in fields:
            if field.name == 'status':
                patterns['active_status'] = model.objects.filter(status='active')
            elif field.name == 'is_active':
                patterns['active_flag'] = model.objects.filter(is_active=True)
            elif field.name == 'created_date':
                patterns['recent_created'] = model.objects.filter(
                    created_date__gte=datetime.now() - timedelta(days=7)
                )
        
        return patterns
    
    def _generate_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations from analysis."""
        recommendations = []
        
        # Check slow queries
        slow_queries = results['optimizations'].get('slow_queries', [])
        if len(slow_queries) > 5:
            recommendations.append(
                f"Found {len(slow_queries)} slow queries. "
                "Focus on optimizing the top 5 slowest queries first."
            )
        
        # Check missing indexes
        missing_indexes = results['optimizations'].get('missing_indexes', [])
        if missing_indexes:
            recommendations.append(
                f"Found {len(missing_indexes)} potential missing indexes. "
                "Review and apply index suggestions after testing."
            )
        
        # Check unused indexes
        index_usage = results['optimizations'].get('index_usage', {})
        unused = index_usage.get('unused_indexes', [])
        if unused:
            recommendations.append(
                f"Found {len(unused)} unused indexes consuming space. "
                "Consider dropping unused indexes to improve write performance."
            )
        
        # Check table maintenance
        table_stats = results['optimizations'].get('table_stats', {})
        if table_stats.get('tables_need_vacuum'):
            recommendations.append(
                "Several tables need VACUUM. "
                "Run VACUUM to reclaim space and update visibility map."
            )
        
        if table_stats.get('bloated_tables'):
            recommendations.append(
                "Table bloat detected. "
                "Consider scheduling VACUUM FULL or using pg_repack during maintenance window."
            )
        
        # General recommendations
        recommendations.extend([
            "Enable pg_stat_statements for better query analysis",
            "Consider connection pooling to reduce connection overhead",
            "Review and update table statistics regularly with ANALYZE",
            "Monitor long-running transactions that can block vacuum"
        ])
        
        return recommendations


class ConnectionPoolManager:
    """
    Manage database connection pooling for optimal performance.
    """
    
    def __init__(self):
        self.pool_stats = {}
        self.config = self._get_pool_config()
    
    def _get_pool_config(self) -> Dict[str, Any]:
        """Get connection pool configuration."""
        return {
            'max_connections': getattr(settings, 'DB_POOL_MAX_CONNECTIONS', 100),
            'min_connections': getattr(settings, 'DB_POOL_MIN_CONNECTIONS', 10),
            'max_overflow': getattr(settings, 'DB_POOL_MAX_OVERFLOW', 20),
            'pool_timeout': getattr(settings, 'DB_POOL_TIMEOUT', 30),
            'recycle_time': getattr(settings, 'DB_POOL_RECYCLE', 3600)
        }
    
    def optimize_pool_settings(self) -> Dict[str, Any]:
        """
        Analyze and optimize connection pool settings.
        """
        recommendations = []
        current_stats = self._get_connection_stats()
        
        # Check if pool size is appropriate
        active_connections = current_stats.get('active_connections', 0)
        max_connections = self.config['max_connections']
        
        if active_connections > max_connections * 0.8:
            recommendations.append({
                'setting': 'max_connections',
                'current': max_connections,
                'recommended': int(max_connections * 1.5),
                'reason': 'Pool frequently at capacity'
            })
        
        # Check for connection leaks
        idle_in_transaction = current_stats.get('idle_in_transaction', 0)
        if idle_in_transaction > 5:
            recommendations.append({
                'issue': 'Connection leak detected',
                'idle_transactions': idle_in_transaction,
                'recommendation': 'Review transaction management and add timeouts'
            })
        
        return {
            'current_config': self.config,
            'current_stats': current_stats,
            'recommendations': recommendations
        }
    
    def _get_connection_stats(self) -> Dict[str, Any]:
        """Get current connection statistics."""
        stats = {}
        
        with connection.cursor() as cursor:
            # Get connection stats
            cursor.execute("""
                SELECT 
                    state,
                    COUNT(*) as count
                FROM pg_stat_activity
                GROUP BY state
            """)
            
            for row in cursor.fetchall():
                state, count = row
                stats[state or 'idle'] = count
            
            stats['total_connections'] = sum(stats.values())
            stats['active_connections'] = stats.get('active', 0)
            stats['idle_in_transaction'] = stats.get('idle in transaction', 0)
        
        return stats