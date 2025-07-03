"""
Optimized Database Migrations

Tools for creating and executing optimized database migrations.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from django.db import migrations, models, connection
from django.db.migrations import Migration, RunSQL
from django.db.migrations.operations.base import Operation
from django.apps import apps
import time

logger = logging.getLogger(__name__)


class OptimizedMigrationExecutor:
    """
    Execute database migrations with performance optimizations.
    """
    
    def __init__(self):
        self.execution_stats = []
    
    def create_optimized_migration(self, operations: List[Operation], 
                                 dependencies: List[Tuple[str, str]],
                                 app_label: str,
                                 migration_name: str) -> Migration:
        """
        Create migration with performance optimizations.
        """
        # Analyze operations for optimization opportunities
        optimized_ops = self._optimize_operations(operations)
        
        # Add performance hints
        optimized_ops = self._add_performance_hints(optimized_ops)
        
        class OptimizedMigration(Migration):
            dependencies = dependencies
            operations = optimized_ops
            
            def apply(self, project_state, schema_editor, collect_sql=False):
                """Apply migration with timing."""
                start_time = time.time()
                result = super().apply(project_state, schema_editor, collect_sql)
                duration = time.time() - start_time
                
                logger.info(
                    f"Migration {app_label}.{migration_name} "
                    f"completed in {duration:.2f}s"
                )
                
                return result
        
        return OptimizedMigration()
    
    def _optimize_operations(self, operations: List[Operation]) -> List[Operation]:
        """Optimize migration operations."""
        optimized = []
        
        # Group operations for batch execution
        create_models = []
        add_fields = []
        create_indexes = []
        
        for op in operations:
            if isinstance(op, migrations.CreateModel):
                create_models.append(op)
            elif isinstance(op, migrations.AddField):
                add_fields.append(op)
            elif isinstance(op, migrations.AddIndex):
                create_indexes.append(op)
            else:
                # Process accumulated operations
                if create_models:
                    optimized.extend(self._optimize_create_models(create_models))
                    create_models = []
                if add_fields:
                    optimized.extend(self._optimize_add_fields(add_fields))
                    add_fields = []
                
                optimized.append(op)
        
        # Process remaining operations
        if create_models:
            optimized.extend(self._optimize_create_models(create_models))
        if add_fields:
            optimized.extend(self._optimize_add_fields(add_fields))
        
        # Defer index creation to end
        if create_indexes:
            optimized.extend(create_indexes)
        
        return optimized
    
    def _optimize_create_models(self, operations: List[migrations.CreateModel]) -> List[Operation]:
        """Optimize CreateModel operations."""
        # Check for foreign key dependencies
        model_names = {op.name for op in operations}
        
        # Sort by dependencies
        sorted_ops = []
        remaining = operations.copy()
        
        while remaining:
            for op in remaining[:]:
                # Check if all FK dependencies are satisfied
                deps_satisfied = True
                for field in op.fields:
                    if isinstance(field[1], models.ForeignKey):
                        related_model = field[1].remote_field.model
                        if isinstance(related_model, str) and related_model in model_names:
                            # Check if dependency is already in sorted list
                            if not any(o.name == related_model for o in sorted_ops):
                                deps_satisfied = False
                                break
                
                if deps_satisfied:
                    sorted_ops.append(op)
                    remaining.remove(op)
            
            # Break infinite loop if no progress
            if len(remaining) == len(operations) - len(sorted_ops):
                sorted_ops.extend(remaining)
                break
        
        return sorted_ops
    
    def _optimize_add_fields(self, operations: List[migrations.AddField]) -> List[Operation]:
        """Optimize AddField operations."""
        # Group by model
        by_model = {}
        for op in operations:
            if op.model_name not in by_model:
                by_model[op.model_name] = []
            by_model[op.model_name].append(op)
        
        optimized = []
        
        # Create batch operations where possible
        for model_name, fields in by_model.items():
            if len(fields) > 3:  # Threshold for batching
                # Create custom batch operation
                batch_op = BatchAddFields(model_name, fields)
                optimized.append(batch_op)
            else:
                optimized.extend(fields)
        
        return optimized
    
    def _add_performance_hints(self, operations: List[Operation]) -> List[Operation]:
        """Add performance hints to operations."""
        enhanced = []
        
        for op in operations:
            # Add hints for large table operations
            if isinstance(op, migrations.AddField) and not op.field.null:
                # Adding non-nullable field to existing table
                enhanced.extend([
                    RunSQL(
                        "-- Adding column with DEFAULT to avoid table rewrite",
                        reverse_sql=migrations.RunSQL.noop
                    ),
                    op
                ])
            elif isinstance(op, migrations.AddIndex):
                # Create index concurrently
                enhanced.append(
                    RunSQL(
                        f"-- Consider CREATE INDEX CONCURRENTLY for large tables",
                        reverse_sql=migrations.RunSQL.noop
                    )
                )
                enhanced.append(op)
            else:
                enhanced.append(op)
        
        return enhanced


class BatchAddFields(Operation):
    """
    Custom operation to add multiple fields in batch.
    """
    
    def __init__(self, model_name: str, field_operations: List[migrations.AddField]):
        self.model_name = model_name
        self.field_operations = field_operations
    
    def state_forwards(self, app_label, state):
        """Update state for all fields."""
        for op in self.field_operations:
            op.state_forwards(app_label, state)
    
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Add all fields in batch."""
        model = from_state.apps.get_model(app_label, self.model_name)
        
        # Start transaction for batch operation
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("BEGIN")
            
            try:
                for op in self.field_operations:
                    op.database_forwards(app_label, schema_editor, from_state, to_state)
                
                cursor.execute("COMMIT")
                logger.info(
                    f"Batch added {len(self.field_operations)} fields "
                    f"to {self.model_name}"
                )
            except Exception as e:
                cursor.execute("ROLLBACK")
                raise
    
    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        """Remove all fields in batch."""
        for op in reversed(self.field_operations):
            op.database_backwards(app_label, schema_editor, from_state, to_state)
    
    def describe(self):
        """Describe the operation."""
        field_names = [op.name for op in self.field_operations]
        return f"Batch add fields {field_names} to {self.model_name}"


class IndexMigrationGenerator:
    """
    Generate optimized index migrations.
    """
    
    def __init__(self):
        self.index_analysis = {}
    
    def generate_index_migration(self, model: models.Model, 
                               index_suggestions: List[Dict[str, Any]]) -> Migration:
        """
        Generate migration for index creation.
        """
        operations = []
        
        for suggestion in index_suggestions:
            if suggestion['type'] == 'single':
                # Single column index
                index = models.Index(
                    fields=[suggestion['field']],
                    name=f"idx_{model._meta.db_table}_{suggestion['field']}"
                )
                operations.append(
                    migrations.AddIndex(
                        model_name=model._meta.model_name,
                        index=index
                    )
                )
            elif suggestion['type'] == 'composite':
                # Composite index
                index = models.Index(
                    fields=suggestion['fields'],
                    name=f"idx_{model._meta.db_table}_{'_'.join(suggestion['fields'])}"[:63]
                )
                operations.append(
                    migrations.AddIndex(
                        model_name=model._meta.model_name,
                        index=index
                    )
                )
            elif suggestion['type'] == 'partial':
                # Partial index (PostgreSQL specific)
                sql = self._generate_partial_index_sql(
                    model._meta.db_table,
                    suggestion['fields'],
                    suggestion['condition']
                )
                operations.append(
                    RunSQL(sql, reverse_sql=RunSQL.noop)
                )
        
        # Add concurrent index creation for large tables
        if self._is_large_table(model):
            operations = self._wrap_concurrent_index_creation(operations, model)
        
        return self._create_migration(
            operations,
            app_label=model._meta.app_label,
            model_name=model._meta.model_name
        )
    
    def _generate_partial_index_sql(self, table_name: str, 
                                  fields: List[str], 
                                  condition: str) -> str:
        """Generate SQL for partial index."""
        index_name = f"idx_{table_name}_{'_'.join(fields)}_partial"[:63]
        field_list = ', '.join(fields)
        
        return f"""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}
        ON {table_name} ({field_list})
        WHERE {condition};
        """
    
    def _is_large_table(self, model: models.Model) -> bool:
        """Check if table is large enough to need concurrent indexing."""
        try:
            # Check row count
            count = model.objects.count()
            return count > 100000  # 100k rows threshold
        except:
            return False
    
    def _wrap_concurrent_index_creation(self, operations: List[Operation], 
                                      model: models.Model) -> List[Operation]:
        """Wrap index operations for concurrent creation."""
        wrapped = []
        
        for op in operations:
            if isinstance(op, migrations.AddIndex):
                # Convert to concurrent SQL
                index = op.index
                fields = ', '.join(index.fields)
                index_name = index.name or f"idx_{model._meta.db_table}_{'_'.join(index.fields)}"[:63]
                
                sql = f"""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}
                ON {model._meta.db_table} ({fields});
                """
                
                wrapped.append(
                    RunSQL(
                        sql,
                        reverse_sql=f"DROP INDEX IF EXISTS {index_name};",
                        state_operations=[op]  # Update state
                    )
                )
            else:
                wrapped.append(op)
        
        return wrapped
    
    def _create_migration(self, operations: List[Operation], 
                         app_label: str, model_name: str) -> Migration:
        """Create migration class."""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        
        class IndexMigration(Migration):
            initial = False
            dependencies = [(app_label, 'auto_latest')]
            operations = operations
            
            def apply(self, project_state, schema_editor, collect_sql=False):
                """Apply with progress tracking."""
                total_ops = len(self.operations)
                
                for i, op in enumerate(self.operations):
                    logger.info(
                        f"Applying index migration {i+1}/{total_ops}: "
                        f"{op.describe()}"
                    )
                    op.state_forwards(app_label, project_state)
                    if not collect_sql:
                        op.database_forwards(
                            app_label, schema_editor, 
                            project_state, project_state
                        )
                
                return project_state
        
        return IndexMigration()
    
    def analyze_existing_indexes(self, model: models.Model) -> Dict[str, Any]:
        """Analyze existing indexes on model."""
        table_name = model._meta.db_table
        
        with connection.cursor() as cursor:
            # Get existing indexes
            cursor.execute("""
                SELECT 
                    indexname,
                    indexdef,
                    tablename,
                    schemaname
                FROM pg_indexes
                WHERE tablename = %s
            """, [table_name])
            
            indexes = []
            for row in cursor.fetchall():
                indexes.append({
                    'name': row[0],
                    'definition': row[1],
                    'table': row[2],
                    'schema': row[3]
                })
            
            # Get index usage stats
            cursor.execute("""
                SELECT 
                    indexrelname,
                    idx_scan,
                    idx_tup_read,
                    idx_tup_fetch
                FROM pg_stat_user_indexes
                WHERE schemaname = 'public'
                AND tablename = %s
            """, [table_name])
            
            usage_stats = {}
            for row in cursor.fetchall():
                usage_stats[row[0]] = {
                    'scans': row[1],
                    'tuples_read': row[2],
                    'tuples_fetched': row[3]
                }
        
        # Analyze effectiveness
        analysis = {
            'total_indexes': len(indexes),
            'indexes': indexes,
            'usage_stats': usage_stats,
            'unused_indexes': [
                idx['name'] for idx in indexes
                if usage_stats.get(idx['name'], {}).get('scans', 0) == 0
            ],
            'recommendations': []
        }
        
        # Add recommendations
        if analysis['unused_indexes']:
            analysis['recommendations'].append(
                f"Consider dropping {len(analysis['unused_indexes'])} unused indexes"
            )
        
        return analysis


class MigrationOptimizationAdvisor:
    """
    Provide advice for optimizing migrations.
    """
    
    @staticmethod
    def analyze_migration(migration: Migration) -> Dict[str, Any]:
        """Analyze migration for optimization opportunities."""
        advice = {
            'operations': len(migration.operations),
            'warnings': [],
            'suggestions': []
        }
        
        for op in migration.operations:
            if isinstance(op, migrations.AddField) and not op.field.null:
                advice['warnings'].append(
                    f"Adding non-nullable field '{op.field.name}' may lock table. "
                    "Consider adding with null=True first, then populate and alter."
                )
            
            elif isinstance(op, migrations.AlterField):
                advice['suggestions'].append(
                    f"AlterField on '{op.name}' may require table rewrite. "
                    "Test on copy of production data."
                )
            
            elif isinstance(op, migrations.RenameField):
                advice['suggestions'].append(
                    f"RenameField '{op.old_name}' -> '{op.new_name}' is metadata only. "
                    "Update application code simultaneously."
                )
            
            elif isinstance(op, RunSQL):
                if 'CREATE INDEX' in op.sql.upper() and 'CONCURRENTLY' not in op.sql.upper():
                    advice['warnings'].append(
                        "CREATE INDEX without CONCURRENTLY will lock table. "
                        "Use CREATE INDEX CONCURRENTLY for zero-downtime deployment."
                    )
        
        return advice