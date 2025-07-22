"""
EnterpriseLand Platform Load Test Scenarios

Comprehensive load test scenarios for platform validation.
"""
from locust import HttpUser, TaskSet, task, between, constant_pacing
import random
import json
from datetime import datetime, timedelta


class InvestmentAnalystBehavior(TaskSet):
    """
    Simulates an investment analyst's typical workflow.
    """
    
    def on_start(self):
        """Initialize user session."""
        # Login
        response = self.client.post("/api/auth/login/", json={
            "email": f"analyst{random.randint(1, 100)}@example.com",
            "password": "testpass123"
        })
        if response.status_code == 200:
            data = response.json()
            self.client.headers['Authorization'] = f"Bearer {data['access_token']}"
            self.user_id = data.get('user_id')
    
    @task(30)
    def view_portfolio_dashboard(self):
        """View main portfolio dashboard."""
        self.client.get("/api/portfolios/", name="/api/portfolios/")
        
        # View specific portfolio details
        portfolio_id = random.randint(1, 50)
        self.client.get(
            f"/api/portfolios/{portfolio_id}/",
            name="/api/portfolios/[id]/"
        )
    
    @task(25)
    def analyze_portfolio_performance(self):
        """Analyze portfolio performance metrics."""
        portfolio_id = random.randint(1, 50)
        
        # Get performance data
        self.client.get(
            f"/api/portfolios/{portfolio_id}/performance/",
            params={
                "periods": "YTD,1Y,3Y,5Y",
                "as_of_date": datetime.now().date().isoformat()
            },
            name="/api/portfolios/[id]/performance/"
        )
        
        # Get analytics
        self.client.get(
            f"/api/portfolios/{portfolio_id}/analytics/",
            params={
                "metrics": "irr,moic,dpi,tvpi",
                "benchmarks": "SP500,MSCI_WORLD"
            },
            name="/api/portfolios/[id]/analytics/"
        )
    
    @task(20)
    def review_market_intelligence(self):
        """Review market intelligence and targets."""
        # View market intelligence dashboard
        self.client.get("/api/market-intelligence/", name="/api/market-intelligence/")
        
        # Search for specific targets
        self.client.get(
            "/api/market-intelligence/targets/",
            params={
                "sectors": "Technology,Healthcare",
                "min_score": 70,
                "limit": 20
            },
            name="/api/market-intelligence/targets/"
        )
        
        # View target details
        target_id = random.randint(1, 200)
        self.client.get(
            f"/api/market-intelligence/targets/{target_id}/",
            name="/api/market-intelligence/targets/[id]/"
        )
    
    @task(15)
    def manage_leads(self):
        """Manage investment leads."""
        # View lead pipeline
        self.client.get(
            "/api/leads/",
            params={"status": "QUALIFIED,CONTACTED"},
            name="/api/leads/"
        )
        
        # Score leads
        lead_ids = [random.randint(1, 500) for _ in range(10)]
        self.client.post(
            "/api/leads/score/",
            json={
                "lead_ids": lead_ids,
                "model_id": "default_model"
            },
            name="/api/leads/score/"
        )
        
        # Update lead status
        lead_id = random.choice(lead_ids)
        self.client.patch(
            f"/api/leads/{lead_id}/",
            json={"status": "MEETING_SCHEDULED"},
            name="/api/leads/[id]/"
        )
    
    @task(10)
    def generate_reports(self):
        """Generate various reports."""
        portfolio_id = random.randint(1, 50)
        
        # Generate quarterly report
        self.client.post(
            f"/api/portfolios/{portfolio_id}/generate_report/",
            json={
                "report_type": "ilpa_quarterly",
                "period_start": "2024-01-01",
                "period_end": "2024-03-31",
                "format": "pdf"
            },
            name="/api/portfolios/[id]/generate_report/"
        )
        
        # Check report status
        report_id = random.randint(1, 1000)
        self.client.get(
            f"/api/portfolios/reports/{report_id}/",
            name="/api/portfolios/reports/[id]/"
        )


class DealTeamBehavior(TaskSet):
    """
    Simulates deal team member workflow.
    """
    
    def on_start(self):
        """Initialize session."""
        response = self.client.post("/api/auth/login/", json={
            "email": f"dealteam{random.randint(1, 50)}@example.com",
            "password": "testpass123"
        })
        if response.status_code == 200:
            data = response.json()
            self.client.headers['Authorization'] = f"Bearer {data['access_token']}"
    
    @task(35)
    def manage_deals(self):
        """Manage active deals."""
        # View deal pipeline
        self.client.get(
            "/api/deals/",
            params={"status": "DUE_DILIGENCE,NEGOTIATION"},
            name="/api/deals/"
        )
        
        # View deal details
        deal_id = random.randint(1, 100)
        self.client.get(f"/api/deals/{deal_id}/", name="/api/deals/[id]/")
        
        # Update deal stage
        self.client.post(
            f"/api/deals/{deal_id}/transition/",
            json={
                "to_stage": "NEGOTIATION",
                "notes": "Proceeding to term sheet negotiation"
            },
            name="/api/deals/[id]/transition/"
        )
    
    @task(30)
    def virtual_data_room(self):
        """Access virtual data room."""
        deal_id = random.randint(1, 100)
        
        # List VDR documents
        self.client.get(
            f"/api/deals/{deal_id}/vdr/documents/",
            name="/api/deals/[id]/vdr/documents/"
        )
        
        # Upload document
        self.client.post(
            f"/api/deals/{deal_id}/vdr/upload/",
            files={'file': ('test.pdf', b'test content', 'application/pdf')},
            name="/api/deals/[id]/vdr/upload/"
        )
        
        # View document
        doc_id = random.randint(1, 500)
        self.client.get(
            f"/api/deals/{deal_id}/vdr/documents/{doc_id}/",
            name="/api/deals/[id]/vdr/documents/[id]/"
        )
    
    @task(20)
    def collaborate_on_deals(self):
        """Collaborate with team members."""
        deal_id = random.randint(1, 100)
        
        # View deal activities
        self.client.get(
            f"/api/deals/{deal_id}/activities/",
            name="/api/deals/[id]/activities/"
        )
        
        # Add comment
        self.client.post(
            f"/api/deals/{deal_id}/comments/",
            json={
                "content": "Updated financial model based on Q4 results",
                "attachments": []
            },
            name="/api/deals/[id]/comments/"
        )
        
        # Schedule meeting
        self.client.post(
            f"/api/deals/{deal_id}/meetings/",
            json={
                "title": "Due Diligence Review",
                "scheduled_at": (datetime.now() + timedelta(days=2)).isoformat(),
                "participants": ["user1", "user2", "user3"]
            },
            name="/api/deals/[id]/meetings/"
        )
    
    @task(15)
    def generate_ic_pack(self):
        """Generate investment committee pack."""
        deal_id = random.randint(1, 100)
        
        self.client.post(
            f"/api/deals/{deal_id}/generate_ic_pack/",
            json={
                "template": "standard",
                "include_sections": [
                    "executive_summary",
                    "financial_analysis",
                    "market_analysis",
                    "risk_assessment",
                    "recommendation"
                ]
            },
            name="/api/deals/[id]/generate_ic_pack/"
        )


class ExecutiveBehavior(TaskSet):
    """
    Simulates executive user behavior (less frequent, dashboard focused).
    """
    
    wait_time = between(5, 10)  # Executives check less frequently
    
    def on_start(self):
        """Initialize session."""
        response = self.client.post("/api/auth/login/", json={
            "email": "executive@example.com",
            "password": "testpass123"
        })
        if response.status_code == 200:
            data = response.json()
            self.client.headers['Authorization'] = f"Bearer {data['access_token']}"
    
    @task(40)
    def view_executive_dashboard(self):
        """View executive dashboard."""
        # Performance overview
        self.client.get("/api/performance/dashboard/overview/")
        
        # Portfolio summary
        self.client.get("/api/portfolios/summary/")
        
        # Key metrics
        self.client.get("/api/analytics/kpis/")
    
    @task(30)
    def review_portfolio_performance(self):
        """Review overall portfolio performance."""
        self.client.post(
            "/api/portfolios/analytics/calculate/",
            json={
                "portfolio_ids": [str(i) for i in range(1, 11)],  # Top 10 portfolios
                "metrics": ["irr", "moic", "tvpi"],
                "start_date": "2024-01-01",
                "end_date": datetime.now().date().isoformat()
            }
        )
    
    @task(20)
    def view_reports(self):
        """View executive reports."""
        # Recent reports
        self.client.get(
            "/api/portfolios/reports/",
            params={
                "report_type": "management",
                "limit": 10
            }
        )
        
        # Download report
        report_id = random.randint(1, 100)
        self.client.get(f"/api/portfolios/reports/{report_id}/download/")
    
    @task(10)
    def check_alerts(self):
        """Check critical alerts."""
        self.client.get(
            "/api/portfolios/alerts/",
            params={"severity": "critical,high"}
        )


class MobileUserBehavior(TaskSet):
    """
    Simulates mobile app user behavior (API-only, lighter requests).
    """
    
    wait_time = between(2, 5)
    
    def on_start(self):
        """Initialize mobile session."""
        response = self.client.post("/api/auth/mobile/login/", json={
            "email": f"mobile{random.randint(1, 200)}@example.com",
            "password": "testpass123",
            "device_id": f"device_{random.randint(1000, 9999)}"
        })
        if response.status_code == 200:
            data = response.json()
            self.client.headers['Authorization'] = f"Bearer {data['access_token']}"
    
    @task(40)
    def quick_portfolio_check(self):
        """Quick portfolio status check."""
        # Summary view
        self.client.get("/api/mobile/portfolios/summary/")
        
        # Recent changes
        self.client.get("/api/mobile/portfolios/recent-changes/")
    
    @task(30)
    def view_notifications(self):
        """Check notifications."""
        self.client.get("/api/mobile/notifications/")
        
        # Mark as read
        notification_ids = [random.randint(1, 100) for _ in range(5)]
        self.client.post(
            "/api/mobile/notifications/mark-read/",
            json={"notification_ids": notification_ids}
        )
    
    @task(20)
    def quick_actions(self):
        """Perform quick actions."""
        # Approve/reject items
        self.client.get("/api/mobile/pending-approvals/")
        
        # Quick approve
        item_id = random.randint(1, 50)
        self.client.post(
            f"/api/mobile/approve/{item_id}/",
            json={"action": "approve", "notes": "Approved via mobile"}
        )
    
    @task(10)
    def sync_offline_data(self):
        """Sync offline data."""
        self.client.post(
            "/api/mobile/sync/",
            json={
                "last_sync": (datetime.now() - timedelta(hours=2)).isoformat(),
                "device_id": f"device_{random.randint(1000, 9999)}"
            }
        )


# User classes for different load patterns
class StandardUser(HttpUser):
    """Standard mixed-behavior user."""
    tasks = [InvestmentAnalystBehavior]
    wait_time = between(1, 3)


class PowerUser(HttpUser):
    """Power user with intense activity."""
    tasks = [InvestmentAnalystBehavior, DealTeamBehavior]
    wait_time = constant_pacing(1)  # Constant 1 request/second


class MixedWorkloadUser(HttpUser):
    """Realistic mixed workload."""
    tasks = {
        InvestmentAnalystBehavior: 40,
        DealTeamBehavior: 30,
        ExecutiveBehavior: 10,
        MobileUserBehavior: 20
    }
    wait_time = between(1, 5)


class SpikeTestUser(HttpUser):
    """User for spike testing."""
    tasks = [InvestmentAnalystBehavior]
    wait_time = between(0.1, 0.5)  # Very aggressive


class EnduranceTestUser(HttpUser):
    """User for endurance testing."""
    tasks = {
        InvestmentAnalystBehavior: 50,
        DealTeamBehavior: 30,
        MobileUserBehavior: 20
    }
    wait_time = between(2, 8)  # More realistic pacing