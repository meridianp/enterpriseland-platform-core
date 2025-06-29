"""
Request and Response Transformers

Handles data transformation between client and backend services.
"""

import json
import xmltodict
import dicttoxml
from typing import Any, Dict, Optional
from jsonpath_ng import parse
import jinja2

from .exceptions import TransformationError


class BaseTransformer:
    """Base class for transformers"""
    
    def transform(self, data: Any, transform_type: str, 
                 config: Dict[str, Any]) -> Any:
        """
        Transform data based on type and config.
        
        Args:
            data: Data to transform
            transform_type: Type of transformation
            config: Transformation configuration
            
        Returns:
            Transformed data
        """
        if transform_type == 'none':
            return data
        
        method_name = f"_{transform_type}_transform"
        method = getattr(self, method_name, None)
        
        if not method:
            raise TransformationError(
                f"Unknown transform type: {transform_type}"
            )
        
        try:
            return method(data, config)
        except Exception as e:
            raise TransformationError(f"Transformation failed: {e}")


class RequestTransformer(BaseTransformer):
    """Transforms incoming requests before forwarding to backend"""
    
    def _json_transform(self, data: Any, config: Dict[str, Any]) -> Any:
        """
        JSON transformation using JSONPath or templates.
        
        Config options:
        - mapping: Dict mapping source paths to target paths
        - template: Jinja2 template for transformation
        - add_fields: Fields to add
        - remove_fields: Fields to remove
        """
        if not isinstance(data, dict):
            return data
        
        result = {}
        
        # Apply field mapping
        if 'mapping' in config:
            for source_path, target_path in config['mapping'].items():
                # Extract value using JSONPath
                jsonpath_expr = parse(source_path)
                matches = jsonpath_expr.find(data)
                
                if matches:
                    # Set value at target path
                    self._set_nested_value(result, target_path, matches[0].value)
        
        # Apply template
        if 'template' in config:
            template = jinja2.Template(config['template'])
            rendered = template.render(data=data, **result)
            result = json.loads(rendered)
        
        # Add fields
        if 'add_fields' in config:
            for key, value in config['add_fields'].items():
                self._set_nested_value(result, key, value)
        
        # Remove fields
        if 'remove_fields' in config:
            for field in config['remove_fields']:
                self._remove_nested_value(result, field)
        
        return result or data
    
    def _xml_transform(self, data: Any, config: Dict[str, Any]) -> Any:
        """Transform between JSON and XML"""
        if isinstance(data, dict):
            # JSON to XML
            root_name = config.get('root_element', 'root')
            xml_data = dicttoxml.dicttoxml(
                data,
                custom_root=root_name,
                attr_type=False
            )
            return xml_data.decode('utf-8')
        elif isinstance(data, (str, bytes)):
            # XML to JSON
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            parsed = xmltodict.parse(data)
            
            # Remove root element if configured
            if config.get('remove_root', True) and len(parsed) == 1:
                return list(parsed.values())[0]
            
            return parsed
        
        return data
    
    def _custom_transform(self, data: Any, config: Dict[str, Any]) -> Any:
        """
        Custom transformation using Python code.
        
        Config:
        - code: Python code to execute (data variable available)
        """
        if 'code' not in config:
            return data
        
        # Create safe execution environment
        safe_globals = {
            'json': json,
            'data': data,
        }
        
        # Execute transformation code
        exec(config['code'], safe_globals)
        
        return safe_globals.get('result', data)
    
    def _set_nested_value(self, obj: dict, path: str, value: Any):
        """Set value at nested path"""
        keys = path.split('.')
        current = obj
        
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
    
    def _remove_nested_value(self, obj: dict, path: str):
        """Remove value at nested path"""
        keys = path.split('.')
        current = obj
        
        for key in keys[:-1]:
            if key not in current:
                return
            current = current[key]
        
        current.pop(keys[-1], None)


class ResponseTransformer(BaseTransformer):
    """Transforms backend responses before returning to client"""
    
    def _json_transform(self, data: Any, config: Dict[str, Any]) -> Any:
        """JSON response transformation"""
        if not isinstance(data, dict):
            return data
        
        result = {}
        
        # Field mapping
        if 'mapping' in config:
            for source_path, target_path in config['mapping'].items():
                jsonpath_expr = parse(source_path)
                matches = jsonpath_expr.find(data)
                
                if matches:
                    self._set_nested_value(result, target_path, matches[0].value)
        else:
            result = data.copy()
        
        # Rename fields
        if 'rename_fields' in config:
            for old_name, new_name in config['rename_fields'].items():
                if old_name in result:
                    result[new_name] = result.pop(old_name)
        
        # Filter fields (whitelist)
        if 'include_fields' in config:
            filtered = {}
            for field in config['include_fields']:
                if field in result:
                    filtered[field] = result[field]
            result = filtered
        
        # Remove fields (blacklist)
        if 'exclude_fields' in config:
            for field in config['exclude_fields']:
                result.pop(field, None)
        
        # Add metadata
        if config.get('add_metadata', False):
            result['_metadata'] = {
                'transformed': True,
                'service': config.get('service_name', 'unknown'),
                'timestamp': json.dumps(
                    __import__('datetime').datetime.utcnow().isoformat()
                )
            }
        
        return result
    
    def _xml_transform(self, data: Any, config: Dict[str, Any]) -> Any:
        """Transform between JSON and XML for responses"""
        return self._request_xml_transform(data, config)
    
    def _custom_transform(self, data: Any, config: Dict[str, Any]) -> Any:
        """Custom response transformation"""
        if 'code' not in config:
            return data
        
        safe_globals = {
            'json': json,
            'data': data,
        }
        
        exec(config['code'], safe_globals)
        
        return safe_globals.get('result', data)
    
    def _set_nested_value(self, obj: dict, path: str, value: Any):
        """Set value at nested path"""
        keys = path.split('.')
        current = obj
        
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
    
    # Alias for request transformer method
    _request_xml_transform = RequestTransformer._xml_transform


class AggregationTransformer:
    """
    Transforms and merges responses from multiple services.
    """
    
    def merge_responses(self, responses: Dict[str, Any], 
                       template: Optional[Dict[str, Any]] = None) -> Any:
        """
        Merge multiple service responses.
        
        Args:
            responses: Dict of service_name -> response data
            template: Optional merge template
            
        Returns:
            Merged response
        """
        if not template:
            # Simple merge - combine all responses
            return {
                'data': responses,
                'services': list(responses.keys())
            }
        
        # Template-based merge
        return self._apply_template(responses, template)
    
    def _apply_template(self, responses: Dict[str, Any], 
                       template: Dict[str, Any]) -> Any:
        """Apply merge template to responses"""
        result = {}
        
        for key, value in template.items():
            if isinstance(value, str) and value.startswith('$'):
                # Reference to response data
                # Format: $service_name.path.to.field
                parts = value[1:].split('.', 1)
                service_name = parts[0]
                
                if service_name in responses:
                    if len(parts) > 1:
                        # Extract nested field
                        path = parts[1]
                        jsonpath_expr = parse(path)
                        matches = jsonpath_expr.find(responses[service_name])
                        
                        if matches:
                            result[key] = matches[0].value
                    else:
                        # Use entire response
                        result[key] = responses[service_name]
            elif isinstance(value, dict):
                # Nested template
                result[key] = self._apply_template(responses, value)
            elif isinstance(value, list):
                # List template
                result[key] = [
                    self._apply_template(responses, item) 
                    if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                # Static value
                result[key] = value
        
        return result