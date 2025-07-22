"""Data service for managing data sources and queries."""

import logging
from typing import Dict, List, Optional, Any, Union
import json
import asyncio
from contextlib import contextmanager

import psycopg2
import pymongo
import mysql.connector
import redis
import requests
from elasticsearch import Elasticsearch
from django.core.cache import cache
from django.db import connection as django_connection
from django.utils import timezone

from ..models import DataSource, DataSourceConnection, QueryDefinition

logger = logging.getLogger(__name__)


class DataConnector:
    """Base class for data source connectors."""
    
    def connect(self, data_source: DataSource) -> Any:
        """Establish connection to data source."""
        raise NotImplementedError
    
    def disconnect(self, connection: Any):
        """Close connection to data source."""
        raise NotImplementedError
    
    def execute_query(self, connection: Any, query: str, parameters: Dict = None) -> Dict:
        """Execute query and return results."""
        raise NotImplementedError
    
    def test_connection(self, data_source: DataSource) -> bool:
        """Test if connection can be established."""
        try:
            with self.get_connection(data_source) as conn:
                if data_source.test_query:
                    self.execute_query(conn, data_source.test_query)
                return True
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False
    
    @contextmanager
    def get_connection(self, data_source: DataSource):
        """Context manager for connections."""
        conn = None
        try:
            conn = self.connect(data_source)
            yield conn
        finally:
            if conn:
                self.disconnect(conn)


class PostgreSQLConnector(DataConnector):
    """PostgreSQL connector."""
    
    def connect(self, data_source: DataSource):
        """Connect to PostgreSQL database."""
        conn_params = {
            'host': data_source.host,
            'port': data_source.port or 5432,
            'database': data_source.database,
            'user': data_source.username,
            'password': data_source.password,
        }
        
        # Add SSL config if enabled
        if data_source.ssl_enabled and data_source.ssl_config:
            conn_params.update(data_source.ssl_config)
        
        # Add additional options
        if data_source.connection_options:
            conn_params.update(data_source.connection_options)
        
        return psycopg2.connect(**conn_params)
    
    def disconnect(self, connection):
        """Close PostgreSQL connection."""
        connection.close()
    
    def execute_query(self, connection, query: str, parameters: Dict = None) -> Dict:
        """Execute PostgreSQL query."""
        cursor = connection.cursor()
        
        try:
            if parameters:
                cursor.execute(query, parameters)
            else:
                cursor.execute(query)
            
            # Get column names
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            
            # Fetch results
            rows = cursor.fetchall()
            
            return {
                'columns': columns,
                'rows': [dict(zip(columns, row)) for row in rows],
                'row_count': len(rows),
            }
        finally:
            cursor.close()


class MySQLConnector(DataConnector):
    """MySQL connector."""
    
    def connect(self, data_source: DataSource):
        """Connect to MySQL database."""
        config = {
            'host': data_source.host,
            'port': data_source.port or 3306,
            'database': data_source.database,
            'user': data_source.username,
            'password': data_source.password,
        }
        
        # Add SSL config
        if data_source.ssl_enabled and data_source.ssl_config:
            config['ssl_ca'] = data_source.ssl_config.get('ca')
            config['ssl_cert'] = data_source.ssl_config.get('cert')
            config['ssl_key'] = data_source.ssl_config.get('key')
        
        # Add additional options
        if data_source.connection_options:
            config.update(data_source.connection_options)
        
        return mysql.connector.connect(**config)
    
    def disconnect(self, connection):
        """Close MySQL connection."""
        connection.close()
    
    def execute_query(self, connection, query: str, parameters: Dict = None) -> Dict:
        """Execute MySQL query."""
        cursor = connection.cursor(dictionary=True)
        
        try:
            if parameters:
                cursor.execute(query, parameters)
            else:
                cursor.execute(query)
            
            rows = cursor.fetchall()
            columns = list(rows[0].keys()) if rows else []
            
            return {
                'columns': columns,
                'rows': rows,
                'row_count': len(rows),
            }
        finally:
            cursor.close()


class MongoDBConnector(DataConnector):
    """MongoDB connector."""
    
    def connect(self, data_source: DataSource):
        """Connect to MongoDB."""
        connection_string = f"mongodb://"
        
        if data_source.username and data_source.password:
            connection_string += f"{data_source.username}:{data_source.password}@"
        
        connection_string += f"{data_source.host}:{data_source.port or 27017}/"
        
        if data_source.database:
            connection_string += data_source.database
        
        # Add connection options
        if data_source.connection_options:
            params = "&".join(f"{k}={v}" for k, v in data_source.connection_options.items())
            connection_string += f"?{params}"
        
        client = pymongo.MongoClient(connection_string, serverSelectionTimeoutMS=data_source.timeout * 1000)
        return client[data_source.database] if data_source.database else client
    
    def disconnect(self, connection):
        """Close MongoDB connection."""
        connection.client.close()
    
    def execute_query(self, connection, query: str, parameters: Dict = None) -> Dict:
        """Execute MongoDB query."""
        # Parse query as JSON
        query_obj = json.loads(query)
        
        collection_name = query_obj.get('collection')
        operation = query_obj.get('operation', 'find')
        
        collection = connection[collection_name]
        
        if operation == 'find':
            filter_query = query_obj.get('filter', {})
            projection = query_obj.get('projection')
            sort = query_obj.get('sort')
            limit = query_obj.get('limit', 1000)
            
            cursor = collection.find(filter_query, projection)
            
            if sort:
                cursor = cursor.sort(sort)
            
            cursor = cursor.limit(limit)
            
            rows = list(cursor)
            
            # Convert ObjectId to string
            for row in rows:
                if '_id' in row:
                    row['_id'] = str(row['_id'])
            
            columns = list(rows[0].keys()) if rows else []
            
            return {
                'columns': columns,
                'rows': rows,
                'row_count': len(rows),
            }
        
        elif operation == 'aggregate':
            pipeline = query_obj.get('pipeline', [])
            rows = list(collection.aggregate(pipeline))
            
            # Convert ObjectId to string
            for row in rows:
                if '_id' in row:
                    row['_id'] = str(row['_id'])
            
            columns = list(rows[0].keys()) if rows else []
            
            return {
                'columns': columns,
                'rows': rows,
                'row_count': len(rows),
            }
        
        else:
            raise ValueError(f"Unsupported operation: {operation}")


class APIConnector(DataConnector):
    """REST API connector."""
    
    def connect(self, data_source: DataSource):
        """Create API session."""
        session = requests.Session()
        
        # Set authentication
        if data_source.api_key:
            session.headers['Authorization'] = f"Bearer {data_source.api_key}"
        elif data_source.username and data_source.password:
            session.auth = (data_source.username, data_source.password)
        
        # Set default headers
        session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        
        # Add custom headers from connection options
        if data_source.connection_options and 'headers' in data_source.connection_options:
            session.headers.update(data_source.connection_options['headers'])
        
        return session
    
    def disconnect(self, connection):
        """Close API session."""
        connection.close()
    
    def execute_query(self, connection, query: str, parameters: Dict = None) -> Dict:
        """Execute API request."""
        # Parse query as JSON
        query_obj = json.loads(query) if isinstance(query, str) else query
        
        method = query_obj.get('method', 'GET')
        endpoint = query_obj.get('endpoint')
        params = query_obj.get('params', {})
        data = query_obj.get('data')
        
        # Apply parameters
        if parameters:
            params.update(parameters)
        
        # Build full URL
        base_url = query_obj.get('base_url') or connection.headers.get('base_url', '')
        url = f"{base_url}{endpoint}"
        
        # Make request
        response = connection.request(
            method=method,
            url=url,
            params=params,
            json=data,
            timeout=30
        )
        
        response.raise_for_status()
        
        # Parse response
        result = response.json()
        
        # Handle different response formats
        if isinstance(result, list):
            rows = result
        elif isinstance(result, dict) and 'data' in result:
            rows = result['data'] if isinstance(result['data'], list) else [result['data']]
        else:
            rows = [result]
        
        columns = list(rows[0].keys()) if rows else []
        
        return {
            'columns': columns,
            'rows': rows,
            'row_count': len(rows),
        }


class DataSourceService:
    """Service for managing data sources."""
    
    CONNECTOR_MAP = {
        'postgresql': PostgreSQLConnector,
        'mysql': MySQLConnector,
        'mongodb': MongoDBConnector,
        'api': APIConnector,
        'internal': None,  # Uses Django ORM
    }
    
    def get_connector(self, data_source: DataSource) -> DataConnector:
        """Get appropriate connector for data source type."""
        connector_class = self.CONNECTOR_MAP.get(data_source.type)
        
        if not connector_class:
            if data_source.type == 'internal':
                return None  # Handle internally
            raise ValueError(f"Unsupported data source type: {data_source.type}")
        
        return connector_class()
    
    def test_connection(self, data_source_id: str) -> Dict:
        """Test data source connection."""
        data_source = DataSource.objects.get(id=data_source_id)
        
        try:
            if data_source.type == 'internal':
                # Test Django database connection
                with django_connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                success = True
                error = None
            else:
                connector = self.get_connector(data_source)
                success = connector.test_connection(data_source)
                error = None if success else "Connection test failed"
            
            # Update data source status
            data_source.last_tested = timezone.now()
            data_source.is_healthy = success
            data_source.last_error = error or ""
            data_source.status = 'active' if success else 'error'
            data_source.save()
            
            return {
                'success': success,
                'error': error,
                'tested_at': data_source.last_tested.isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            
            # Update data source status
            data_source.last_tested = timezone.now()
            data_source.is_healthy = False
            data_source.last_error = str(e)
            data_source.status = 'error'
            data_source.save()
            
            return {
                'success': False,
                'error': str(e),
                'tested_at': data_source.last_tested.isoformat(),
            }
    
    def create_connection(self, data_source_id: str, user) -> DataSourceConnection:
        """Create a tracked connection to a data source."""
        data_source = DataSource.objects.get(id=data_source_id)
        
        # Generate unique connection ID
        connection_id = f"{data_source.id}:{user.id}:{timezone.now().timestamp()}"
        
        return DataSourceConnection.objects.create(
            data_source=data_source,
            user=user,
            connection_id=connection_id,
            is_active=True
        )
    
    def close_connection(self, connection_id: str):
        """Close a tracked connection."""
        try:
            connection = DataSourceConnection.objects.get(connection_id=connection_id)
            connection.is_active = False
            connection.save()
        except DataSourceConnection.DoesNotExist:
            pass


class QueryExecutor:
    """Execute queries against data sources."""
    
    def __init__(self):
        self.data_source_service = DataSourceService()
    
    def execute(self, data_source: DataSource, query: str, parameters: Dict = None, use_cache: bool = True) -> Dict:
        """Execute a query against a data source."""
        # Check cache
        if use_cache and data_source.enable_caching:
            cache_key = self._get_cache_key(data_source, query, parameters)
            cached_result = cache.get(cache_key)
            
            if cached_result:
                return cached_result
        
        # Execute query
        start_time = timezone.now()
        
        try:
            if data_source.type == 'internal':
                result = self._execute_internal_query(query, parameters)
            else:
                connector = self.data_source_service.get_connector(data_source)
                
                with connector.get_connection(data_source) as conn:
                    result = connector.execute_query(conn, query, parameters)
            
            # Apply row limit
            if len(result['rows']) > data_source.max_rows:
                result['rows'] = result['rows'][:data_source.max_rows]
                result['truncated'] = True
                result['total_rows'] = result['row_count']
                result['row_count'] = len(result['rows'])
            
            # Add metadata
            result['execution_time'] = (timezone.now() - start_time).total_seconds()
            result['data_source'] = {
                'id': str(data_source.id),
                'name': data_source.name,
                'type': data_source.type,
            }
            
            # Cache result
            if use_cache and data_source.enable_caching:
                cache.set(cache_key, result, data_source.cache_duration)
            
            return result
            
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            raise
    
    def execute_query_definition(self, query_def_id: str, parameters: Dict = None) -> Dict:
        """Execute a saved query definition."""
        query_def = QueryDefinition.objects.select_related('data_source').get(id=query_def_id)
        
        # Merge parameters
        final_parameters = query_def.parameters.copy()
        if parameters:
            final_parameters.update(parameters)
        
        # Execute query
        result = self.execute(query_def.data_source, query_def.query, final_parameters)
        
        # Apply transformations
        if query_def.transformations:
            result = self._apply_transformations(result, query_def.transformations)
        
        # Update usage stats
        query_def.usage_count += 1
        query_def.last_used = timezone.now()
        query_def.save(update_fields=['usage_count', 'last_used'])
        
        return result
    
    def _execute_internal_query(self, query: str, parameters: Dict = None) -> Dict:
        """Execute query against Django database."""
        with django_connection.cursor() as cursor:
            if parameters:
                cursor.execute(query, parameters)
            else:
                cursor.execute(query)
            
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            
            return {
                'columns': columns,
                'rows': [dict(zip(columns, row)) for row in rows],
                'row_count': len(rows),
            }
    
    def _get_cache_key(self, data_source: DataSource, query: str, parameters: Dict = None) -> str:
        """Generate cache key for query result."""
        import hashlib
        
        key_parts = [
            'query_result',
            str(data_source.id),
            hashlib.md5(query.encode()).hexdigest(),
            hashlib.md5(json.dumps(parameters or {}, sort_keys=True).encode()).hexdigest(),
        ]
        
        return ":".join(key_parts)
    
    def _apply_transformations(self, result: Dict, transformations: List[Dict]) -> Dict:
        """Apply transformations to query result."""
        # This is a simplified version - implement actual transformation logic
        for transform in transformations:
            transform_type = transform.get('type')
            
            if transform_type == 'rename':
                # Rename columns
                mapping = transform.get('mapping', {})
                for row in result['rows']:
                    for old_name, new_name in mapping.items():
                        if old_name in row:
                            row[new_name] = row.pop(old_name)
                
                # Update column list
                result['columns'] = [mapping.get(col, col) for col in result['columns']]
            
            elif transform_type == 'filter':
                # Filter rows
                condition = transform.get('condition')
                if condition:
                    # Implement filter logic
                    pass
            
            elif transform_type == 'calculate':
                # Add calculated fields
                calculations = transform.get('calculations', [])
                for calc in calculations:
                    field_name = calc.get('name')
                    expression = calc.get('expression')
                    
                    # Implement calculation logic
                    for row in result['rows']:
                        # Simple example - replace with actual expression evaluation
                        row[field_name] = eval(expression, {'row': row})
                    
                    if field_name not in result['columns']:
                        result['columns'].append(field_name)
        
        return result