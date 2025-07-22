"""Visualization models for the reporting module."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator

from core.models.base import GroupFilteredModel

User = get_user_model()


class VisualizationType(models.Model):
    """Available visualization types."""
    
    CATEGORY_CHOICES = [
        ('basic', 'Basic Charts'),
        ('advanced', 'Advanced Charts'),
        ('statistical', 'Statistical'),
        ('geographic', 'Geographic'),
        ('temporal', 'Time-based'),
        ('hierarchical', 'Hierarchical'),
        ('relationship', 'Relationship'),
        ('custom', 'Custom'),
    ]
    
    # Type information
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='basic')
    description = models.TextField(blank=True)
    
    # Configuration
    icon = models.CharField(max_length=50, blank=True)
    component_name = models.CharField(max_length=100, help_text="Frontend component name")
    default_config = JSONField(default=dict, help_text="Default configuration for this type")
    
    # Requirements
    min_dimensions = models.IntegerField(default=1, validators=[MinValueValidator(0)])
    max_dimensions = models.IntegerField(default=2, validators=[MinValueValidator(1)])
    min_measures = models.IntegerField(default=1, validators=[MinValueValidator(0)])
    max_measures = models.IntegerField(default=10, validators=[MinValueValidator(1)])
    
    # Features
    supports_3d = models.BooleanField(default=False)
    supports_animation = models.BooleanField(default=False)
    supports_interaction = models.BooleanField(default=True)
    supports_export = models.BooleanField(default=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['category', 'order', 'name']
        
    def __str__(self):
        return self.display_name


class Visualization(GroupFilteredModel):
    """Individual visualization configuration."""
    
    # Basic information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.ForeignKey(VisualizationType, on_delete=models.PROTECT, related_name='visualizations')
    
    # Data configuration
    data_source = models.ForeignKey('DataSource', on_delete=models.SET_NULL, null=True, blank=True)
    query = models.ForeignKey('QueryDefinition', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Chart configuration
    dimensions = JSONField(default=list, help_text="Dimension fields (x-axis, categories)")
    measures = JSONField(default=list, help_text="Measure fields (y-axis, values)")
    filters = JSONField(default=list, help_text="Applied filters")
    
    # Visual configuration
    configuration = JSONField(default=dict, help_text="Chart-specific configuration")
    colors = JSONField(default=dict, help_text="Color configuration")
    
    # Layout
    width = models.IntegerField(null=True, blank=True, help_text="Width in pixels")
    height = models.IntegerField(null=True, blank=True, help_text="Height in pixels")
    responsive = models.BooleanField(default=True)
    
    # Interaction
    interactive = models.BooleanField(default=True)
    drill_down_config = JSONField(null=True, blank=True, help_text="Drill-down configuration")
    tooltip_config = JSONField(null=True, blank=True, help_text="Tooltip configuration")
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    is_template = models.BooleanField(default=False)
    
    # Ownership
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_visualizations')
    is_public = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['name']
        
    def __str__(self):
        return f"{self.name} ({self.type.display_name})"
    
    def clone(self, name_suffix=" (Copy)"):
        """Create a copy of this visualization."""
        viz_copy = Visualization.objects.create(
            name=f"{self.name}{name_suffix}",
            description=self.description,
            type=self.type,
            data_source=self.data_source,
            query=self.query,
            dimensions=self.dimensions,
            measures=self.measures,
            filters=self.filters,
            configuration=self.configuration,
            colors=self.colors,
            width=self.width,
            height=self.height,
            responsive=self.responsive,
            interactive=self.interactive,
            drill_down_config=self.drill_down_config,
            tooltip_config=self.tooltip_config,
            tags=self.tags,
            created_by=self.created_by,
            group=self.group
        )
        
        return viz_copy


class ChartConfiguration(models.Model):
    """Predefined chart configurations."""
    
    visualization_type = models.ForeignKey(VisualizationType, on_delete=models.CASCADE, related_name='presets')
    
    # Configuration details
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    configuration = JSONField(help_text="Complete chart configuration")
    
    # Example data
    example_data = JSONField(null=True, blank=True, help_text="Example data for preview")
    preview_image = models.URLField(blank=True, null=True)
    
    # Metadata
    is_default = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['visualization_type', 'order', 'name']
        unique_together = [['visualization_type', 'name']]
        
    def __str__(self):
        return f"{self.name} - {self.visualization_type.display_name}"