"""Tests for reporting module models."""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from accounts.models import UserGroup
from ..models import (
    Report, ReportTemplate, Dashboard, Widget,
    DataSource, Metric, Visualization, VisualizationType,
    Alert, ReportShare, DashboardShare
)

User = get_user_model()


class ReportModelTest(TestCase):
    """Test Report model."""
    
    def setUp(self):
        """Set up test data."""
        self.group = UserGroup.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.user.group = self.group
        self.user.save()
        
        self.template = ReportTemplate.objects.create(
            name="Test Template",
            description="Test template description",
            category="executive",
            template_config={"sections": ["summary"]}
        )
    
    def test_create_report(self):
        """Test creating a report."""
        report = Report.objects.create(
            name="Test Report",
            description="Test report description",
            type="standard",
            owner=self.user,
            group=self.group,
            template=self.template,
            configuration={"key": "value"}
        )
        
        self.assertEqual(report.name, "Test Report")
        self.assertEqual(report.status, "draft")
        self.assertEqual(report.version, 1)
        self.assertEqual(report.owner, self.user)
        self.assertEqual(report.group, self.group)
    
    def test_report_status_transitions(self):
        """Test report status transitions."""
        report = Report.objects.create(
            name="Test Report",
            owner=self.user,
            group=self.group
        )
        
        # Test publish transition
        self.assertEqual(report.status, "draft")
        report.publish()
        report.save()
        self.assertEqual(report.status, "published")
        self.assertEqual(report.version, 2)
        
        # Test archive transition
        report.archive()
        report.save()
        self.assertEqual(report.status, "archived")
        
        # Test restore transition
        report.restore()
        report.save()
        self.assertEqual(report.status, "draft")
    
    def test_report_clone(self):
        """Test cloning a report."""
        original = Report.objects.create(
            name="Original Report",
            description="Original description",
            owner=self.user,
            group=self.group,
            tags=["tag1", "tag2"]
        )
        
        # Add a data source
        data_source = DataSource.objects.create(
            name="Test DB",
            type="postgresql",
            owner=self.user,
            group=self.group
        )
        original.data_sources.add(data_source)
        
        # Clone the report
        clone = original.clone()
        
        self.assertEqual(clone.name, "Original Report (Copy)")
        self.assertEqual(clone.description, original.description)
        self.assertEqual(clone.tags, original.tags)
        self.assertEqual(clone.owner, self.user)
        self.assertIn(data_source, clone.data_sources.all())
        self.assertNotEqual(clone.id, original.id)


class DashboardModelTest(TestCase):
    """Test Dashboard model."""
    
    def setUp(self):
        """Set up test data."""
        self.group = UserGroup.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.user.group = self.group
        self.user.save()
    
    def test_create_dashboard(self):
        """Test creating a dashboard."""
        dashboard = Dashboard.objects.create(
            name="Test Dashboard",
            description="Test dashboard description",
            layout_type="grid",
            theme="light",
            owner=self.user,
            group=self.group,
            auto_refresh=True,
            refresh_interval=300
        )
        
        self.assertEqual(dashboard.name, "Test Dashboard")
        self.assertEqual(dashboard.layout_type, "grid")
        self.assertTrue(dashboard.auto_refresh)
        self.assertEqual(dashboard.refresh_interval, 300)
    
    def test_dashboard_clone(self):
        """Test cloning a dashboard."""
        original = Dashboard.objects.create(
            name="Original Dashboard",
            owner=self.user,
            group=self.group,
            theme="dark",
            tags=["analytics", "sales"]
        )
        
        # Add widgets
        widget1 = Widget.objects.create(
            dashboard=original,
            name="Widget 1",
            type="chart",
            position=0,
            group=self.group
        )
        widget2 = Widget.objects.create(
            dashboard=original,
            name="Widget 2",
            type="metric",
            position=1,
            group=self.group
        )
        
        # Clone the dashboard
        clone = original.clone()
        
        self.assertEqual(clone.name, "Original Dashboard (Copy)")
        self.assertEqual(clone.theme, original.theme)
        self.assertEqual(clone.widgets.count(), 2)
        
        # Check widgets were cloned
        cloned_widgets = clone.widgets.all().order_by('position')
        self.assertEqual(cloned_widgets[0].name, "Widget 1")
        self.assertEqual(cloned_widgets[1].name, "Widget 2")


class DataSourceModelTest(TestCase):
    """Test DataSource model."""
    
    def setUp(self):
        """Set up test data."""
        self.group = UserGroup.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.user.group = self.group
        self.user.save()
    
    def test_create_data_source(self):
        """Test creating a data source."""
        data_source = DataSource.objects.create(
            name="Production DB",
            description="Production PostgreSQL database",
            type="postgresql",
            host="db.example.com",
            port=5432,
            database="production",
            username="readonly",
            password="secret",
            owner=self.user,
            group=self.group
        )
        
        self.assertEqual(data_source.name, "Production DB")
        self.assertEqual(data_source.type, "postgresql")
        self.assertEqual(data_source.status, "active")
        self.assertTrue(data_source.ssl_enabled)
        self.assertTrue(data_source.enable_caching)
    
    def test_connection_string(self):
        """Test connection string generation."""
        data_source = DataSource.objects.create(
            name="Test DB",
            type="postgresql",
            host="localhost",
            port=5432,
            database="testdb",
            username="testuser",
            owner=self.user,
            group=self.group
        )
        
        conn_string = data_source.get_connection_string()
        self.assertEqual(conn_string, "postgresql://testuser:***@localhost:5432/testdb")


class MetricModelTest(TestCase):
    """Test Metric model."""
    
    def setUp(self):
        """Set up test data."""
        self.group = UserGroup.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.user.group = self.group
        self.user.save()
    
    def test_create_metric(self):
        """Test creating a metric."""
        metric = Metric.objects.create(
            name="total_revenue",
            display_name="Total Revenue",
            description="Total revenue in USD",
            type="simple",
            aggregation="sum",
            format="currency",
            decimals=2,
            prefix="$",
            category="Financial",
            owner=self.user,
            group=self.group
        )
        
        self.assertEqual(metric.display_name, "Total Revenue")
        self.assertEqual(metric.format, "currency")
        self.assertEqual(metric.prefix, "$")
        self.assertEqual(metric.decimals, 2)


class AlertModelTest(TestCase):
    """Test Alert model."""
    
    def setUp(self):
        """Set up test data."""
        self.group = UserGroup.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.user.group = self.group
        self.user.save()
        
        self.metric = Metric.objects.create(
            name="error_rate",
            display_name="Error Rate",
            type="simple",
            owner=self.user,
            group=self.group
        )
    
    def test_create_alert(self):
        """Test creating an alert."""
        alert = Alert.objects.create(
            name="High Error Rate",
            description="Alert when error rate exceeds 5%",
            severity="warning",
            metric=self.metric,
            notification_channels=["email", "slack"],
            recipients=["admin@example.com"],
            check_interval=300,
            owner=self.user,
            group=self.group
        )
        
        self.assertEqual(alert.name, "High Error Rate")
        self.assertEqual(alert.status, "active")
        self.assertEqual(alert.severity, "warning")
        self.assertIn("email", alert.notification_channels)
        self.assertEqual(alert.check_interval, 300)


class ShareModelTest(TestCase):
    """Test sharing models."""
    
    def setUp(self):
        """Set up test data."""
        self.group = UserGroup.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.user.group = self.group
        self.user.save()
        
        self.report = Report.objects.create(
            name="Test Report",
            owner=self.user,
            group=self.group
        )
        
        self.dashboard = Dashboard.objects.create(
            name="Test Dashboard",
            owner=self.user,
            group=self.group
        )
    
    def test_report_share(self):
        """Test sharing a report."""
        share = ReportShare.objects.create(
            report=self.report,
            share_type="link",
            permission="view",
            shared_by=self.user,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        self.assertEqual(share.share_type, "link")
        self.assertEqual(share.permission, "view")
        self.assertTrue(share.is_active)
        self.assertFalse(share.is_expired())
        self.assertIsNotNone(share.share_token)
    
    def test_dashboard_share_with_embed(self):
        """Test sharing a dashboard with embed options."""
        share = DashboardShare.objects.create(
            dashboard=self.dashboard,
            share_type="embed",
            permission="view",
            shared_by=self.user,
            embed_width="100%",
            embed_height="600px",
            show_title=True
        )
        
        self.assertEqual(share.share_type, "embed")
        self.assertEqual(share.embed_width, "100%")
        self.assertTrue(share.show_title)
        
        # Test embed code generation
        embed_code = share.get_embed_code()
        self.assertIn("iframe", embed_code)
        self.assertIn(str(share.share_token), embed_code)
        self.assertIn('width="100%"', embed_code)
        self.assertIn('height="600px"', embed_code)