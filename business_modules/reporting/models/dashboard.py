"""Dashboard models for the reporting module."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator

from core.models.base import GroupFilteredModel

User = get_user_model()


class Dashboard(GroupFilteredModel):
    """Interactive dashboard with multiple widgets."""
    
    LAYOUT_CHOICES = [
        ('grid', 'Grid Layout'),
        ('flex', 'Flexible Layout'),
        ('masonry', 'Masonry Layout'),
        ('responsive', 'Responsive Layout'),
    ]
    
    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('professional', 'Professional'),
        ('colorful', 'Colorful'),
        ('minimal', 'Minimal'),
    ]
    
    # Basic information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    slug = models.SlugField(unique=True, null=True, blank=True)
    
    # Layout and appearance
    layout_type = models.CharField(max_length=20, choices=LAYOUT_CHOICES, default='grid')
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='light')
    configuration = JSONField(default=dict, help_text="Dashboard configuration")
    
    # Display settings
    is_public = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False, help_text="Default dashboard for users")
    auto_refresh = models.BooleanField(default=False)
    refresh_interval = models.IntegerField(
        default=300,
        validators=[MinValueValidator(10), MaxValueValidator(3600)],
        help_text="Auto-refresh interval in seconds"
    )
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Icon identifier")
    
    # Ownership and collaboration
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_dashboards')
    collaborators = models.ManyToManyField(User, related_name='collaborative_dashboards', blank=True)
    
    # Performance
    cache_widgets = models.BooleanField(default=True)
    lazy_load = models.BooleanField(default=True, help_text="Lazy load widgets for performance")
    
    class Meta:
        ordering = ['name']
        permissions = [
            ('can_publish_dashboard', 'Can publish dashboards'),
            ('can_share_dashboard', 'Can share dashboards'),
            ('can_set_default_dashboard', 'Can set default dashboard'),
        ]
        
    def __str__(self):
        return self.name
    
    def clone(self, user=None):
        """Create a copy of this dashboard."""
        dashboard_copy = Dashboard.objects.create(
            name=f"{self.name} (Copy)",
            description=self.description,
            layout_type=self.layout_type,
            theme=self.theme,
            configuration=self.configuration,
            auto_refresh=self.auto_refresh,
            refresh_interval=self.refresh_interval,
            tags=self.tags,
            icon=self.icon,
            owner=user or self.owner,
            group=self.group
        )
        
        # Clone widgets
        for widget in self.widgets.all():
            widget.clone(dashboard=dashboard_copy)
            
        return dashboard_copy


class Widget(GroupFilteredModel):
    """Individual widget on a dashboard."""
    
    TYPE_CHOICES = [
        ('chart', 'Chart'),
        ('metric', 'Metric'),
        ('table', 'Table'),
        ('text', 'Text'),
        ('image', 'Image'),
        ('map', 'Map'),
        ('list', 'List'),
        ('timeline', 'Timeline'),
        ('custom', 'Custom'),
    ]
    
    SIZE_CHOICES = [
        ('xs', 'Extra Small'),
        ('sm', 'Small'),
        ('md', 'Medium'),
        ('lg', 'Large'),
        ('xl', 'Extra Large'),
        ('full', 'Full Width'),
    ]
    
    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name='widgets')
    
    # Widget configuration
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    size = models.CharField(max_length=10, choices=SIZE_CHOICES, default='md')
    
    # Position and layout
    position = models.IntegerField(default=0, help_text="Widget position in dashboard")
    row = models.IntegerField(default=0)
    column = models.IntegerField(default=0)
    width = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(12)])
    height = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(12)])
    
    # Data configuration
    data_source = models.ForeignKey('DataSource', on_delete=models.SET_NULL, null=True, blank=True)
    query = JSONField(null=True, blank=True, help_text="Query configuration")
    visualization = models.ForeignKey('Visualization', on_delete=models.SET_NULL, null=True, blank=True)
    metric = models.ForeignKey('Metric', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Display configuration
    configuration = JSONField(default=dict, help_text="Widget-specific configuration")
    style = JSONField(default=dict, help_text="Custom styling")
    
    # Behavior
    is_interactive = models.BooleanField(default=True)
    drill_down_enabled = models.BooleanField(default=False)
    export_enabled = models.BooleanField(default=True)
    
    # Performance
    cache_duration = models.IntegerField(
        default=300,
        validators=[MinValueValidator(0), MaxValueValidator(3600)],
        help_text="Cache duration in seconds"
    )
    
    class Meta:
        ordering = ['dashboard', 'position']
        unique_together = [['dashboard', 'position']]
        
    def __str__(self):
        return f"{self.name} ({self.dashboard.name})"
    
    def clone(self, dashboard=None):
        """Create a copy of this widget."""
        widget_copy = Widget.objects.create(
            dashboard=dashboard or self.dashboard,
            name=self.name,
            type=self.type,
            size=self.size,
            position=self.position,
            row=self.row,
            column=self.column,
            width=self.width,
            height=self.height,
            data_source=self.data_source,
            query=self.query,
            visualization=self.visualization,
            metric=self.metric,
            configuration=self.configuration,
            style=self.style,
            is_interactive=self.is_interactive,
            drill_down_enabled=self.drill_down_enabled,
            export_enabled=self.export_enabled,
            cache_duration=self.cache_duration,
            group=self.group
        )
        
        return widget_copy


class DashboardLayout(GroupFilteredModel):
    """Saved dashboard layout configurations."""
    
    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name='layouts')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    # Layout data
    layout_data = JSONField(help_text="Complete layout configuration")
    is_default = models.BooleanField(default=False)
    
    # Device-specific layouts
    device_type = models.CharField(
        max_length=20,
        choices=[
            ('desktop', 'Desktop'),
            ('tablet', 'Tablet'),
            ('mobile', 'Mobile'),
            ('all', 'All Devices'),
        ],
        default='all'
    )
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        ordering = ['dashboard', 'name']
        unique_together = [['dashboard', 'name', 'device_type']]
        
    def __str__(self):
        return f"{self.name} - {self.dashboard.name}"