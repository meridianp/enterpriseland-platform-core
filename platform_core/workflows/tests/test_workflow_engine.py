"""
Test Workflow Engine
"""

import pytest
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import Mock, patch

from platform_core.workflows.models import (
    WorkflowDefinition, WorkflowInstance, WorkflowTask,
    WorkflowTransition, WorkflowTemplate
)
from platform_core.workflows.engine import WorkflowEngine, workflow_engine
from platform_core.workflows.exceptions import (
    WorkflowError, WorkflowNotFoundError, WorkflowPermissionError
)
from platform_core.workflows.examples import (
    SimpleApprovalWorkflow, DocumentReviewWorkflow,
    DataProcessingWorkflow, OnboardingWorkflow
)


User = get_user_model()


class TestWorkflowEngine(TestCase):
    """Test workflow engine functionality"""
    
    def setUp(self):
        # Create test users
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.manager = User.objects.create_user(
            username='manager',
            email='manager@example.com',
            password='testpass123'
        )
        
        # Create test group
        from accounts.models import Group
        self.group = Group.objects.create(
            name='Test Company',
            slug='test-company'
        )
        self.user.group = self.group
        self.user.save()
        self.manager.group = self.group
        self.manager.save()
        
        # Create workflow engine
        self.engine = WorkflowEngine()
        
        # Register test workflows
        self.engine.register_workflow(SimpleApprovalWorkflow)
        self.engine.register_workflow(DocumentReviewWorkflow)
    
    def test_register_workflow(self):
        """Test workflow registration"""
        # Check workflow is registered
        self.assertIn('platform.simple_approval', self.engine._workflow_registry)
        
        # Get workflow class
        workflow_class = self.engine.get_workflow_class('platform.simple_approval')
        self.assertEqual(workflow_class, SimpleApprovalWorkflow)
    
    def test_unregister_workflow(self):
        """Test workflow unregistration"""
        # Register a workflow
        self.engine.register_workflow(DataProcessingWorkflow)
        self.assertIn('platform.data_processing', self.engine._workflow_registry)
        
        # Unregister it
        self.engine.unregister_workflow('platform.data_processing')
        self.assertNotIn('platform.data_processing', self.engine._workflow_registry)
    
    def test_start_workflow(self):
        """Test starting a workflow"""
        # Create workflow definition
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.simple_approval',
            name='Simple Approval',
            workflow_type='approval',
            flow_class='platform_core.workflows.examples.SimpleApprovalWorkflow',
            group=self.group
        )
        
        # Start workflow
        instance = self.engine.start_workflow(
            workflow_id='platform.simple_approval',
            user=self.user,
            title='Test Approval',
            amount=1000
        )
        
        # Check instance created
        self.assertIsNotNone(instance)
        self.assertEqual(instance.definition, definition)
        self.assertEqual(instance.started_by, self.user)
        self.assertEqual(instance.title, 'Test Approval')
        self.assertEqual(instance.status, 'started')
        self.assertEqual(instance.context_data['amount'], 1000)
        
        # Check tasks created
        tasks = instance.tasks.all()
        self.assertTrue(tasks.exists())
        self.assertGreaterEqual(tasks.count(), 3)  # Submit, approval levels, complete
    
    def test_start_workflow_permission_denied(self):
        """Test starting workflow without permission"""
        # Create workflow with permission
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.restricted',
            name='Restricted Workflow',
            workflow_type='approval',
            flow_class='platform_core.workflows.examples.SimpleApprovalWorkflow',
            start_permission='workflows.start_restricted',
            group=self.group
        )
        
        # Try to start without permission
        with self.assertRaises(WorkflowPermissionError):
            self.engine.start_workflow(
                workflow_id='platform.restricted',
                user=self.user
            )
    
    def test_get_workflow_instance(self):
        """Test getting workflow instance"""
        # Create instance
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.simple_approval',
            name='Simple Approval',
            group=self.group
        )
        instance = WorkflowInstance.objects.create(
            definition=definition,
            instance_id='test-instance-123',
            title='Test Instance',
            started_by=self.user,
            group=self.group
        )
        
        # Get instance
        retrieved = self.engine.get_workflow_instance('test-instance-123', self.user)
        self.assertEqual(retrieved, instance)
    
    def test_get_user_tasks(self):
        """Test getting user tasks"""
        # Create workflow and tasks
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.test',
            name='Test Workflow',
            group=self.group
        )
        instance = WorkflowInstance.objects.create(
            definition=definition,
            instance_id='test-123',
            started_by=self.user,
            group=self.group
        )
        
        # Create tasks
        task1 = WorkflowTask.objects.create(
            workflow=instance,
            task_id='task1',
            name='Task 1',
            assigned_to=self.user,
            status='assigned',
            group=self.group
        )
        task2 = WorkflowTask.objects.create(
            workflow=instance,
            task_id='task2',
            name='Task 2',
            assigned_to=self.manager,
            status='assigned',
            group=self.group
        )
        task3 = WorkflowTask.objects.create(
            workflow=instance,
            task_id='task3',
            name='Task 3',
            assigned_to=self.user,
            status='completed',
            group=self.group
        )
        
        # Get user tasks
        user_tasks = self.engine.get_user_tasks(self.user)
        self.assertEqual(len(user_tasks), 2)
        self.assertIn(task1, user_tasks)
        self.assertIn(task3, user_tasks)
        
        # Get only assigned tasks
        assigned_tasks = self.engine.get_user_tasks(self.user, status='assigned')
        self.assertEqual(len(assigned_tasks), 1)
        self.assertEqual(assigned_tasks[0], task1)
    
    def test_execute_task_start(self):
        """Test starting a task"""
        # Create task
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.test',
            name='Test Workflow',
            group=self.group
        )
        instance = WorkflowInstance.objects.create(
            definition=definition,
            started_by=self.user,
            group=self.group
        )
        task = WorkflowTask.objects.create(
            workflow=instance,
            task_id='test-task',
            name='Test Task',
            assigned_to=self.user,
            status='assigned',
            group=self.group
        )
        
        # Execute start action
        updated_task = self.engine.execute_task(
            task_id=str(task.id),
            user=self.user,
            action='start'
        )
        
        # Check task updated
        self.assertEqual(updated_task.status, 'started')
        self.assertIsNotNone(updated_task.started_at)
    
    def test_execute_task_complete(self):
        """Test completing a task"""
        # Create workflow with tasks
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.test',
            name='Test Workflow',
            group=self.group
        )
        instance = WorkflowInstance.objects.create(
            definition=definition,
            started_by=self.user,
            group=self.group
        )
        
        task1 = WorkflowTask.objects.create(
            workflow=instance,
            task_id='task1',
            name='Task 1',
            assigned_to=self.user,
            status='started',
            group=self.group
        )
        task2 = WorkflowTask.objects.create(
            workflow=instance,
            task_id='task2',
            name='Task 2',
            status='created',
            group=self.group
        )
        
        # Create transition
        transition = WorkflowTransition.objects.create(
            workflow=instance,
            from_task=task1,
            to_task=task2
        )
        
        # Complete task
        updated_task = self.engine.execute_task(
            task_id=str(task1.id),
            user=self.user,
            action='complete',
            data={'result': 'approved'}
        )
        
        # Check task completed
        self.assertEqual(updated_task.status, 'completed')
        self.assertIsNotNone(updated_task.completed_at)
        self.assertEqual(updated_task.completed_by, self.user)
        self.assertEqual(updated_task.output_data['result'], 'approved')
        
        # Check next task activated
        task2.refresh_from_db()
        self.assertEqual(task2.status, 'assigned')
    
    def test_workflow_completion(self):
        """Test workflow completion when all tasks done"""
        # Create workflow
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.test',
            name='Test Workflow',
            group=self.group
        )
        instance = WorkflowInstance.objects.create(
            definition=definition,
            started_by=self.user,
            status='started',
            group=self.group
        )
        
        # Create completed tasks
        task1 = WorkflowTask.objects.create(
            workflow=instance,
            task_id='task1',
            name='Task 1',
            status='completed',
            group=self.group
        )
        task2 = WorkflowTask.objects.create(
            workflow=instance,
            task_id='task2',
            name='Task 2',
            status='completed',
            group=self.group
        )
        
        # Check workflow completion
        self.engine._check_workflow_completion(instance)
        
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'completed')
        self.assertIsNotNone(instance.completed_at)
    
    def test_create_from_template(self):
        """Test creating workflow from template"""
        # Create definition and template
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.template_workflow',
            name='Template Workflow',
            flow_class='platform_core.workflows.examples.SimpleApprovalWorkflow',
            group=self.group
        )
        
        template = WorkflowTemplate.objects.create(
            template_id='approval-template',
            name='Approval Template',
            definition=definition,
            customizable_fields=['approval_timeout_hours', 'auto_approve_amount'],
            default_values={
                'approval_timeout_hours': 24,
                'auto_approve_amount': 500
            },
            group=self.group
        )
        
        # Register workflow
        self.engine.register_workflow(SimpleApprovalWorkflow)
        
        # Create from template
        instance = self.engine.create_from_template(
            template_id='approval-template',
            user=self.user,
            title='Template Instance',
            approval_timeout_hours=48,
            amount=1000
        )
        
        # Check instance created
        self.assertIsNotNone(instance)
        self.assertEqual(instance.title, 'Template Instance')
        self.assertEqual(instance.status, 'started')
        self.assertEqual(instance.context_data['approval_timeout_hours'], 48)
        self.assertEqual(instance.context_data['amount'], 1000)
        
        # Check template usage updated
        template.refresh_from_db()
        self.assertEqual(template.times_used, 1)


class TestWorkflowIntegration(TestCase):
    """Test workflow integration scenarios"""
    
    def setUp(self):
        # Create test data
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        from accounts.models import Group
        self.group = Group.objects.create(
            name='Test Company',
            slug='test-company'
        )
        self.user.group = self.group
        self.user.save()
        
        # Register workflows
        workflow_engine.register_workflow(SimpleApprovalWorkflow)
        workflow_engine.register_workflow(DocumentReviewWorkflow)
        workflow_engine.register_workflow(OnboardingWorkflow)
    
    def test_approval_workflow_flow(self):
        """Test complete approval workflow flow"""
        # Create definition
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.simple_approval',
            name='Simple Approval',
            flow_class='platform_core.workflows.examples.SimpleApprovalWorkflow',
            group=self.group
        )
        
        # Start workflow
        instance = workflow_engine.start_workflow(
            workflow_id='platform.simple_approval',
            user=self.user,
            title='Purchase Approval',
            amount=5000,
            approval_timeout_hours=24
        )
        
        # Check initial state
        self.assertEqual(instance.status, 'started')
        
        # Get submission task
        submit_task = instance.tasks.get(task_id='submit')
        self.assertEqual(submit_task.status, 'created')
        
        # Complete submission
        workflow_engine.execute_task(
            task_id=str(submit_task.id),
            user=self.user,
            action='complete',
            data={'description': 'New laptop purchase'}
        )
        
        # Check approval task created
        approval_task = instance.tasks.get(task_id='approve_level_1')
        self.assertEqual(approval_task.status, 'assigned')
        self.assertIsNotNone(approval_task.due_date)
        
        # Approve task
        workflow_engine.execute_task(
            task_id=str(approval_task.id),
            user=self.user,
            action='complete',
            data={'approved': True, 'comments': 'Approved for IT upgrade'}
        )
        
        # Check final approval task
        final_approval = instance.tasks.get(task_id='approve_level_2')
        self.assertEqual(final_approval.status, 'assigned')
        
        # Complete final approval
        workflow_engine.execute_task(
            task_id=str(final_approval.id),
            user=self.user,
            action='complete',
            data={'approved': True}
        )
        
        # Check completion task
        complete_task = instance.tasks.get(task_id='complete')
        self.assertEqual(complete_task.status, 'assigned')
        
        # Complete workflow
        workflow_engine.execute_task(
            task_id=str(complete_task.id),
            user=self.user,
            action='complete'
        )
        
        # Check workflow completed
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'completed')
        self.assertEqual(instance.completed_task_count, 4)
    
    def test_document_review_with_skip(self):
        """Test document review workflow with step skipping"""
        # Create definition
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.document_review',
            name='Document Review',
            flow_class='platform_core.workflows.examples.DocumentReviewWorkflow',
            group=self.group
        )
        
        # Start workflow without legal review
        instance = workflow_engine.start_workflow(
            workflow_id='platform.document_review',
            user=self.user,
            title='Policy Document Review',
            document_id='DOC-123',
            require_legal_review=False
        )
        
        # Check legal review task is skipped
        legal_task = instance.tasks.get(task_id='legal_review')
        self.assertEqual(legal_task.status, 'skipped')
        
        # Complete other tasks
        for task_id in ['upload', 'initial_review', 'final_approval']:
            task = instance.tasks.get(task_id=task_id)
            if task.status in ['created', 'assigned']:
                workflow_engine.execute_task(
                    task_id=str(task.id),
                    user=self.user,
                    action='complete'
                )
    
    @patch('platform_core.workflows.examples.logger')
    def test_automated_workflow_execution(self, mock_logger):
        """Test automated workflow execution"""
        # Create definition
        definition = WorkflowDefinition.objects.create(
            workflow_id='platform.data_processing',
            name='Data Processing',
            flow_class='platform_core.workflows.examples.DataProcessingWorkflow',
            group=self.group
        )
        
        # Create and execute workflow
        workflow = DataProcessingWorkflow()
        instance = WorkflowInstance.objects.create(
            definition=definition,
            instance_id='auto-123',
            started_by=self.user,
            context_data={
                'data_source': 'TEST_DB',
                'processing_type': 'aggregate',
                'notification_emails': ['admin@example.com']
            },
            group=self.group
        )
        
        workflow._instance = instance
        workflow._definition = definition
        
        # Execute
        result = workflow.execute()
        
        # Check execution
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('records_processed', result)
        
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'completed')
        self.assertIsNotNone(instance.context_data['result'])