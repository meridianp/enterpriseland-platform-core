# Reporting and Business Intelligence Module

A comprehensive reporting and business intelligence solution for the EnterpriseLand platform, providing powerful analytics, visualization, and data insights capabilities.

## Features

### Core Capabilities

- **Report Builder**: Drag-and-drop interface for creating custom reports
- **Dashboard Designer**: Create interactive dashboards with customizable widgets
- **Data Visualization**: 15+ chart types including line, bar, pie, heatmaps, and geographic maps
- **Real-time Analytics**: Live data updates and streaming analytics
- **Advanced Analytics**: Time series, cohort, funnel, and predictive analytics
- **Multiple Data Sources**: Connect to PostgreSQL, MySQL, MongoDB, APIs, and more
- **Export Capabilities**: Export to PDF, Excel, CSV, JSON, and images
- **Scheduling**: Automated report generation and distribution
- **Collaboration**: Share reports and dashboards with team members
- **Alerts**: Set up notifications based on metric thresholds

### Key Components

1. **Reports**
   - Create from templates or custom build
   - Version control and history
   - Parameter support for dynamic content
   - Caching for performance

2. **Dashboards**
   - Grid, flex, and responsive layouts
   - Multiple themes (light, dark, professional)
   - Auto-refresh capabilities
   - Widget library

3. **Data Sources**
   - Secure credential storage
   - Connection pooling
   - Query caching
   - Health monitoring

4. **Visualizations**
   - Interactive charts with drill-down
   - Custom color schemes
   - Export individual charts
   - Real-time updates

5. **Metrics & KPIs**
   - Business metric definitions
   - Calculated and composite metrics
   - Historical tracking
   - Target and threshold management

## Installation

The module is automatically installed as part of the EnterpriseLand platform. To enable it:

```python
# In settings.py
INSTALLED_APPS = [
    # ...
    'business_modules.reporting',
]
```

## API Endpoints

### Reports
- `GET/POST /api/reporting/reports/` - List/create reports
- `GET/PUT/DELETE /api/reporting/reports/{id}/` - Manage specific report
- `POST /api/reporting/reports/{id}/execute/` - Execute report
- `POST /api/reporting/reports/{id}/export/` - Export report
- `POST /api/reporting/reports/{id}/share/` - Share report

### Dashboards
- `GET/POST /api/reporting/dashboards/` - List/create dashboards
- `GET/PUT/DELETE /api/reporting/dashboards/{id}/` - Manage specific dashboard
- `GET /api/reporting/dashboards/{id}/widgets/` - Get dashboard widgets
- `POST /api/reporting/dashboards/{id}/share/` - Share dashboard

### Data Sources
- `GET/POST /api/reporting/data-sources/` - List/create data sources
- `POST /api/reporting/data-sources/{id}/test-connection/` - Test connection
- `POST /api/reporting/data-sources/{id}/execute-query/` - Execute query

### Metrics
- `GET/POST /api/reporting/metrics/` - List/create metrics
- `POST /api/reporting/metrics/{id}/calculate/` - Calculate metric value
- `GET /api/reporting/metrics/{id}/history/` - Get metric history

### Analytics
- `GET /api/reporting/analytics/overview/` - Analytics overview
- `GET /api/reporting/analytics/usage/` - Usage statistics
- `GET /api/reporting/analytics/performance/` - Performance metrics

## Usage Examples

### Creating a Report

```python
from business_modules.reporting.models import Report
from business_modules.reporting.services import ReportService

# Create a report from template
service = ReportService()
report = service.create_from_template(
    template_id='executive-summary-template',
    data={
        'name': 'Q4 Executive Summary',
        'description': 'Quarterly business review',
        'data_source_ids': ['prod-db-id'],
        'tags': ['quarterly', 'executive']
    },
    user=request.user
)

# Execute the report
report_data = service.get_report_data(
    report_id=str(report.id),
    parameters={'quarter': 'Q4', 'year': 2024}
)
```

### Creating a Dashboard

```python
from business_modules.reporting.models import Dashboard, Widget

# Create dashboard
dashboard = Dashboard.objects.create(
    name='Sales Dashboard',
    description='Real-time sales metrics',
    layout_type='grid',
    theme='professional',
    auto_refresh=True,
    refresh_interval=300,  # 5 minutes
    owner=request.user,
    group=request.user.group
)

# Add a metric widget
widget = Widget.objects.create(
    dashboard=dashboard,
    name='Total Revenue',
    type='metric',
    size='md',
    position=0,
    metric_id='total-revenue-metric',
    configuration={
        'show_trend': True,
        'show_sparkline': True,
        'color': 'green'
    },
    group=request.user.group
)
```

### Setting Up a Data Source

```python
from business_modules.reporting.models import DataSource
from business_modules.reporting.services import DataSourceService

# Create data source
data_source = DataSource.objects.create(
    name='Production Database',
    type='postgresql',
    host='db.example.com',
    port=5432,
    database='production',
    username='analytics_user',
    password='secure_password',  # Will be encrypted
    ssl_enabled=True,
    owner=request.user,
    group=request.user.group
)

# Test connection
service = DataSourceService()
result = service.test_connection(str(data_source.id))
```

### Creating an Alert

```python
from business_modules.reporting.models import Alert, AlertCondition

# Create alert
alert = Alert.objects.create(
    name='High Error Rate Alert',
    description='Alert when error rate exceeds 5%',
    severity='critical',
    metric_id='error-rate-metric',
    notification_channels=['email', 'slack'],
    recipients=['ops-team@example.com'],
    check_interval=60,  # Check every minute
    owner=request.user,
    group=request.user.group
)

# Add condition
condition = AlertCondition.objects.create(
    field='value',
    operator='gt',
    value='5',
    timeframe='current'
)
alert.conditions.add(condition)
```

## Configuration

### Module Settings

```python
# Reporting module settings
REPORTING_CACHE_TIMEOUT = 3600  # 1 hour
REPORTING_MAX_EXPORT_ROWS = 100000
REPORTING_ENABLE_REALTIME = True
REPORTING_ENABLE_PREDICTIVE = True
REPORTING_DEFAULT_THEME = 'professional'
REPORTING_EXPORT_FORMATS = ['pdf', 'excel', 'csv', 'json', 'png']
REPORTING_MAX_CONCURRENT_REPORTS = 10
REPORTING_DATA_RETENTION_DAYS = 90
```

### Data Source Types

The module supports the following data source types:
- PostgreSQL
- MySQL
- MongoDB
- Elasticsearch
- REST APIs
- GraphQL APIs
- CSV/Excel files
- Google Sheets
- Internal Django database

### Visualization Types

Available visualization types:
- Line Chart
- Bar Chart (vertical/horizontal)
- Pie/Donut Chart
- Scatter Plot
- Heatmap
- Treemap
- Geographic Map
- Gantt Chart
- Funnel Chart
- Waterfall Chart
- Radar Chart
- Bubble Chart
- Sankey Diagram
- Box Plot
- Histogram

## Permissions

The module includes granular permissions:

- `reporting.view_report` - View reports
- `reporting.create_report` - Create reports
- `reporting.edit_report` - Edit reports
- `reporting.delete_report` - Delete reports
- `reporting.export_report` - Export reports
- `reporting.share_report` - Share reports
- `reporting.view_dashboard` - View dashboards
- `reporting.create_dashboard` - Create dashboards
- `reporting.edit_dashboard` - Edit dashboards
- `reporting.delete_dashboard` - Delete dashboards
- `reporting.manage_data_sources` - Manage data sources
- `reporting.execute_analytics` - Execute analytics queries
- `reporting.schedule_reports` - Schedule reports

## Best Practices

1. **Performance**
   - Use caching for frequently accessed reports
   - Implement pagination for large datasets
   - Use aggregated data for dashboards
   - Schedule heavy reports during off-peak hours

2. **Security**
   - Always use encrypted connections for data sources
   - Implement row-level security where needed
   - Regularly rotate data source credentials
   - Audit report access and exports

3. **Data Quality**
   - Validate data sources regularly
   - Implement data quality checks
   - Document metric calculations
   - Version control report definitions

4. **User Experience**
   - Start with templates for common use cases
   - Use consistent color schemes
   - Provide clear metric descriptions
   - Enable drill-down for detailed analysis

## Troubleshooting

### Common Issues

1. **Report execution timeout**
   - Increase query timeout in data source settings
   - Optimize queries using indexes
   - Consider using materialized views

2. **Export failures**
   - Check available disk space
   - Verify export format compatibility
   - Increase memory limits for large exports

3. **Real-time updates not working**
   - Verify WebSocket connection
   - Check Redis connectivity
   - Ensure proper CORS configuration

4. **Data source connection errors**
   - Test connection with provided tool
   - Verify network connectivity
   - Check firewall rules
   - Validate credentials

## Development

### Extending the Module

1. **Adding a new visualization type**
   ```python
   # In visualizations/custom.py
   from .base import BaseVisualization
   
   class CustomChart(BaseVisualization):
       def render(self, data, config):
           # Implementation
           pass
   ```

2. **Creating a custom data connector**
   ```python
   # In data_sources/connectors/custom.py
   from .base import DataConnector
   
   class CustomConnector(DataConnector):
       def connect(self, data_source):
           # Implementation
           pass
   ```

3. **Adding a new export format**
   ```python
   # In exports/formats/custom.py
   from .base import BaseExporter
   
   class CustomExporter(BaseExporter):
       def export(self, report_data, options):
           # Implementation
           pass
   ```

### Testing

Run tests with:
```bash
python manage.py test business_modules.reporting
```

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review API documentation at `/api/reporting/docs/`
3. Contact the platform team

## License

This module is part of the EnterpriseLand platform and follows the same licensing terms.