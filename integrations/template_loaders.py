"""
Template loader interfaces for the integrations app.

This module provides abstract interfaces for loading templates from various sources.
Modules can implement these interfaces to provide their own template storage.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class TemplateLoader(ABC):
    """Abstract base class for template loaders."""
    
    @abstractmethod
    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a template by ID.
        
        Args:
            template_id: Unique identifier for the template
            
        Returns:
            Dictionary with template data including:
            - subject: Email subject template
            - html_content: HTML body template
            - text_content: Optional plain text template
            - metadata: Optional metadata dict
            
            Returns None if template not found.
        """
        pass
    
    @abstractmethod
    def list_templates(self, category: Optional[str] = None) -> list[Dict[str, Any]]:
        """
        List available templates.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of template summaries
        """
        pass


class DefaultTemplateLoader(TemplateLoader):
    """Default template loader that returns None for all requests."""
    
    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Return None - no templates available by default."""
        return None
    
    def list_templates(self, category: Optional[str] = None) -> list[Dict[str, Any]]:
        """Return empty list - no templates available by default."""
        return []


# Global template loader instance
_template_loader: TemplateLoader = DefaultTemplateLoader()


def set_template_loader(loader: TemplateLoader) -> None:
    """Set the global template loader."""
    global _template_loader
    _template_loader = loader


def get_template_loader() -> TemplateLoader:
    """Get the current template loader."""
    return _template_loader