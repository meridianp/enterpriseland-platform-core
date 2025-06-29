"""
Example Workflow Implementations

Demonstrates how to create workflows using the platform's workflow system.
"""

from datetime import timedelta
from django.utils import timezone

from .base import (
    ModuleWorkflow, BaseApprovalWorkflow, BaseProcessWorkflow,
    BaseAutomatedWorkflow
)


class SimpleApprovalWorkflow(BaseApprovalWorkflow):
    """
    Simple two-level approval workflow.
    
    Flow:
    1. Submit for approval
    2. Level 1 approval (Manager)
    3. Level 2 approval (Director)
    4. Complete
    """
    
    workflow_id = "platform.simple_approval"
    workflow_name = "Simple Approval"
    workflow_description = "A simple two-level approval process"
    workflow_version = "1.0.0"
    
    # Approval configuration
    approval_levels = 2
    rejection_allowed = True
    
    # Permissions
    start_permission = "workflows.start_approval"
    view_permission = "workflows.view_approval"
    
    # Configuration schema
    config_schema = {
        "type": "object",
        "properties": {
            "auto_approve_amount": {
                "type": "number",
                "description": "Amount below which auto-approval applies"
            },
            "approval_timeout_hours": {
                "type": "integer",
                "description": "Hours before approval times out",
                "default": 48
            }
        }
    }
    
    def _create_initial_tasks(self):
        """Create approval workflow tasks"""
        super()._create_initial_tasks()
        
        # Set specific properties for approval tasks
        timeout_hours = self.get_context('approval_timeout_hours', 48)
        
        # Update Level 1 approval
        level1_task = self.get_task('approve_level_1')
        if level1_task:
            level1_task.assigned_role = 'Manager'
            level1_task.due_date = timezone.now() + timedelta(hours=timeout_hours)
            level1_task.description = 'Manager approval required'
            level1_task.save()
        
        # Update Level 2 approval
        level2_task = self.get_task('approve_level_2')
        if level2_task:
            level2_task.assigned_role = 'Director'
            level2_task.due_date = timezone.now() + timedelta(hours=timeout_hours * 2)
            level2_task.description = 'Director approval required for final sign-off'
            level2_task.save()
    
    def get_task(self, task_id):
        """Helper to get a task by ID"""
        try:
            return self._instance.tasks.get(task_id=task_id)
        except:
            return None
    
    def should_auto_approve(self, task):
        """Check if task should be auto-approved"""
        amount = self.get_context('amount', 0)
        auto_approve_limit = self.get_context('auto_approve_amount', 0)
        
        if auto_approve_limit and amount < auto_approve_limit:
            return True
        
        return False


class DocumentReviewWorkflow(BaseProcessWorkflow):
    """
    Document review and approval workflow.
    
    Flow:
    1. Upload document
    2. Initial review
    3. Legal review (if required)
    4. Final approval
    5. Publish
    """
    
    workflow_id = "platform.document_review"
    workflow_name = "Document Review"
    workflow_description = "Review and approve documents before publication"
    workflow_version = "1.0.0"
    
    # Process steps
    process_steps = [
        ('upload', 'Upload Document', 'user'),
        ('initial_review', 'Initial Review', 'user'),
        ('legal_review', 'Legal Review', 'user'),
        ('final_approval', 'Final Approval', 'approval'),
        ('publish', 'Publish Document', 'system'),
    ]
    
    allow_skip = True  # Legal review can be skipped
    
    config_schema = {
        "type": "object",
        "properties": {
            "require_legal_review": {
                "type": "boolean",
                "description": "Whether legal review is required",
                "default": True
            },
            "document_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Allowed document types"
            }
        }
    }
    
    def _create_initial_tasks(self):
        """Create document review tasks"""
        super()._create_initial_tasks()
        
        # Check if legal review is required
        require_legal = self.get_context('require_legal_review', True)
        
        if not require_legal:
            # Skip legal review task
            legal_task = self.get_task('legal_review')
            if legal_task:
                legal_task.skip(reason="Legal review not required")
                legal_task.save()
    
    def _handle_publish(self, task):
        """System task handler for publishing"""
        # Get document data
        document_id = self.get_context('document_id')
        
        if not document_id:
            raise ValueError("No document ID provided")
        
        # Simulate document publishing
        # In real implementation, this would integrate with document management
        publish_data = {
            'published_at': timezone.now().isoformat(),
            'published_by': 'system',
            'document_id': document_id,
            'status': 'published'
        }
        
        # Update context
        self.set_context('publish_result', publish_data)
        
        return publish_data


class DataProcessingWorkflow(BaseAutomatedWorkflow):
    """
    Automated data processing workflow.
    
    Steps:
    1. Validate input data
    2. Process data
    3. Generate report
    4. Send notifications
    """
    
    workflow_id = "platform.data_processing"
    workflow_name = "Data Processing"
    workflow_description = "Automated data processing and reporting"
    workflow_version = "1.0.0"
    workflow_type = "automated"
    
    # Automation configuration
    retry_on_failure = True
    max_retries = 3
    retry_delay = 300  # 5 minutes
    
    config_schema = {
        "type": "object",
        "properties": {
            "data_source": {
                "type": "string",
                "description": "Data source identifier"
            },
            "processing_type": {
                "type": "string",
                "enum": ["aggregate", "transform", "analyze"],
                "description": "Type of processing to perform"
            },
            "notification_emails": {
                "type": "array",
                "items": {"type": "string", "format": "email"},
                "description": "Email addresses for notifications"
            }
        },
        "required": ["data_source", "processing_type"]
    }
    
    def _execute_automation(self):
        """Execute the data processing"""
        # Get configuration
        data_source = self.get_context('data_source')
        processing_type = self.get_context('processing_type')
        
        # Step 1: Validate data
        validation_result = self._validate_data(data_source)
        if not validation_result['valid']:
            raise ValueError(f"Data validation failed: {validation_result['errors']}")
        
        self.set_context('validation_result', validation_result)
        
        # Step 2: Process data
        processing_result = self._process_data(
            data_source,
            processing_type,
            validation_result['data']
        )
        
        self.set_context('processing_result', processing_result)
        
        # Step 3: Generate report
        report = self._generate_report(processing_result)
        self.set_context('report', report)
        
        # Step 4: Send notifications
        self._send_notifications(report)
        
        return {
            'status': 'completed',
            'records_processed': processing_result.get('count', 0),
            'report_id': report.get('id'),
            'completed_at': timezone.now().isoformat()
        }
    
    def _validate_data(self, data_source):
        """Validate input data"""
        # Simulate data validation
        return {
            'valid': True,
            'data': {
                'source': data_source,
                'record_count': 1000,
                'validated_at': timezone.now().isoformat()
            },
            'errors': []
        }
    
    def _process_data(self, data_source, processing_type, data):
        """Process the data"""
        # Simulate data processing
        return {
            'type': processing_type,
            'count': data.get('record_count', 0),
            'results': {
                'aggregated': 100,
                'transformed': 900,
                'errors': 0
            },
            'processed_at': timezone.now().isoformat()
        }
    
    def _generate_report(self, processing_result):
        """Generate processing report"""
        # Simulate report generation
        return {
            'id': f"report_{timezone.now().timestamp()}",
            'title': 'Data Processing Report',
            'summary': processing_result,
            'generated_at': timezone.now().isoformat()
        }
    
    def _send_notifications(self, report):
        """Send notification emails"""
        emails = self.get_context('notification_emails', [])
        
        if emails:
            # In real implementation, use platform notification service
            for email in emails:
                logger.info(f"Sending report notification to {email}")


class OnboardingWorkflow(BaseProcessWorkflow):
    """
    Employee onboarding workflow.
    
    Flow:
    1. Create accounts
    2. Assign equipment
    3. Complete training
    4. Manager introduction
    5. HR final check
    """
    
    workflow_id = "platform.employee_onboarding"
    workflow_name = "Employee Onboarding"
    workflow_description = "Complete onboarding process for new employees"
    workflow_version = "1.0.0"
    
    process_steps = [
        ('create_accounts', 'Create User Accounts', 'system'),
        ('assign_equipment', 'Assign Equipment', 'user'),
        ('complete_training', 'Complete Training', 'user'),
        ('manager_intro', 'Manager Introduction', 'user'),
        ('hr_final_check', 'HR Final Check', 'approval'),
    ]
    
    parallel_execution = False  # Steps must be sequential
    
    config_schema = {
        "type": "object",
        "properties": {
            "employee_name": {"type": "string"},
            "employee_email": {"type": "string", "format": "email"},
            "department": {"type": "string"},
            "manager_email": {"type": "string", "format": "email"},
            "start_date": {"type": "string", "format": "date"}
        },
        "required": ["employee_name", "employee_email", "department"]
    }
    
    def _create_initial_tasks(self):
        """Create onboarding tasks with assignments"""
        super()._create_initial_tasks()
        
        # Assign tasks to appropriate roles
        equipment_task = self.get_task('assign_equipment')
        if equipment_task:
            equipment_task.assigned_role = 'IT Support'
            equipment_task.form_data = {
                "fields": [
                    {"name": "laptop_serial", "type": "text", "label": "Laptop Serial Number"},
                    {"name": "phone_assigned", "type": "boolean", "label": "Phone Assigned"},
                    {"name": "access_card", "type": "text", "label": "Access Card Number"}
                ]
            }
            equipment_task.save()
        
        training_task = self.get_task('complete_training')
        if training_task:
            training_task.assigned_to = None  # Assigned to new employee
            training_task.description = "Complete mandatory training modules"
            training_task.save()
        
        manager_task = self.get_task('manager_intro')
        if manager_task:
            # Assign to manager based on context
            manager_email = self.get_context('manager_email')
            if manager_email:
                # In real implementation, look up user by email
                manager_task.description = f"Introduction meeting with {manager_email}"
            manager_task.save()
        
        hr_task = self.get_task('hr_final_check')
        if hr_task:
            hr_task.assigned_role = 'HR'
            hr_task.description = "Final onboarding checklist verification"
            hr_task.save()
    
    def _handle_create_accounts(self, task):
        """System task to create user accounts"""
        employee_email = self.get_context('employee_email')
        employee_name = self.get_context('employee_name')
        
        # Simulate account creation
        accounts_created = {
            'email_account': employee_email,
            'active_directory': f"{employee_email.split('@')[0]}",
            'systems': ['gitlab', 'jira', 'slack'],
            'created_at': timezone.now().isoformat()
        }
        
        self.set_context('accounts_created', accounts_created)
        
        return accounts_created