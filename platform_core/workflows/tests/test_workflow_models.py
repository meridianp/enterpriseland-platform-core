"""
Test Workflow Models
"""

import pytest
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta

from platform_core.workflows.models import (
    WorkflowDefinition, WorkflowInstance, WorkflowTask,
    WorkflowTransition, WorkflowTemplate
)


User = get_user_model()


class TestWorkflowDefinition(TestCase):
    """Test WorkflowDefinition model"""
    
    def setUp(self):
        from accounts.models import Group
        self.group = Group.objects.create(
            name='Test Company',
            slug='test-company'
        )
        
        from platform_core.modules.models import ModuleManifest
        self.module = ModuleManifest.objects.create(
            module_id='test.module',
            name='Test Module',
            version='1.0.0',
            group=self.group
        )
    
    def test_create_workflow_definition(self):
        """Test creating a workflow definition"""
        definition = WorkflowDefinition.objects.create(
            workflow_id='test.workflow',
            name='Test Workflow',
            description='A test workflow',
            version='1.0.0',
            workflow_type='approval',
            module=self.module,
            flow_class='test.workflows.TestFlow',
            config_schema={'type': 'object'},
            default_config={'timeout': 3600},
            tags=['test', 'approval'],
            group=self.group
        )
        
        self.assertEqual(definition.workflow_id, 'test.workflow')
        self.assertEqual(definition.name, 'Test Workflow')
        self.assertEqual(definition.workflow_type, 'approval')
        self.assertTrue(definition.is_active)
        self.assertEqual(definition.times_used, 0)
    
    def test_unique_workflow_id(self):
        """Test workflow_id uniqueness"""
        WorkflowDefinition.objects.create(
            workflow_id='unique.workflow',
            name='Workflow 1',
            group=self.group
        )
        
        with self.assertRaises(Exception):
            WorkflowDefinition.objects.create(
                workflow_id='unique.workflow',
                name='Workflow 2',
                group=self.group
            )
    
    def test_workflow_definition_str(self):
        """Test string representation"""
        definition = WorkflowDefinition.objects.create(
            workflow_id='test.workflow',
            name='Test Workflow',
            group=self.group
        )
        
        self.assertEqual(str(definition), 'Test Workflow (test.workflow)')


class TestWorkflowInstance(TestCase):
    """Test WorkflowInstance model"""
    
    def setUp(self):
        from accounts.models import Group
        self.group = Group.objects.create(
            name='Test Company',
            slug='test-company'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.group = self.group
        self.user.save()
        
        self.definition = WorkflowDefinition.objects.create(
            workflow_id='test.workflow',
            name='Test Workflow',
            group=self.group
        )
    
    def test_create_workflow_instance(self):
        """Test creating a workflow instance"""
        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            instance_id='instance-123',
            title='Test Instance',
            started_by=self.user,
            context_data={'key': 'value'},
            configuration={'timeout': 3600},
            due_date=timezone.now() + timedelta(days=7),
            group=self.group
        )
        
        self.assertEqual(instance.instance_id, 'instance-123')
        self.assertEqual(instance.title, 'Test Instance')
        self.assertEqual(instance.status, 'created')
        self.assertEqual(instance.started_by, self.user)
        self.assertEqual(instance.task_count, 0)
        self.assertEqual(instance.completed_task_count, 0)
    
    def test_workflow_status_transitions(self):
        """Test workflow status transitions"""
        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            instance_id='instance-456',
            started_by=self.user,
            group=self.group
        )
        
        # Test start transition
        self.assertTrue(instance.can_start())
        instance.start(user=self.user)
        self.assertEqual(instance.status, 'started')
        self.assertIsNotNone(instance.started_at)
        
        # Test complete transition
        self.assertTrue(instance.can_complete())
        instance.complete()
        self.assertEqual(instance.status, 'completed')
        self.assertIsNotNone(instance.completed_at)
        self.assertIsNotNone(instance.execution_time)
    
    def test_workflow_fail_transition(self):
        """Test workflow fail transition"""
        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            instance_id='instance-789',
            started_by=self.user,
            status='started',
            group=self.group
        )
        
        # Test fail transition
        self.assertTrue(instance.can_fail())
        instance.fail(error_message='Test error')
        self.assertEqual(instance.status, 'failed')
        self.assertEqual(instance.error_message, 'Test error')
        self.assertIsNotNone(instance.completed_at)
    
    def test_workflow_cancel_transition(self):
        """Test workflow cancel transition"""
        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            instance_id='instance-999',
            started_by=self.user,
            status='started',
            group=self.group
        )
        
        # Test cancel transition
        self.assertTrue(instance.can_cancel())
        instance.cancel(reason='User requested')
        self.assertEqual(instance.status, 'cancelled')
        self.assertEqual(instance.error_message, 'Cancelled: User requested')
    
    def test_get_progress_percentage(self):
        """Test progress calculation"""
        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            started_by=self.user,
            task_count=10,
            completed_task_count=3,
            group=self.group
        )
        
        self.assertEqual(instance.get_progress_percentage(), 30)
        
        # Test with no tasks
        instance.task_count = 0
        self.assertEqual(instance.get_progress_percentage(), 0)
    
    def test_can_edit_permissions(self):
        """Test edit permissions"""
        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            started_by=self.user,
            group=self.group
        )
        
        # User who started can edit
        self.assertTrue(instance.can_edit(self.user))
        
        # Other user cannot edit
        other_user = User.objects.create_user(
            username='other',
            email='other@example.com'
        )
        self.assertFalse(instance.can_edit(other_user))
        
        # Assigned user can edit
        instance.current_assignee = other_user
        instance.save()
        self.assertTrue(instance.can_edit(other_user))
        
        # Participant can edit
        instance.participants.add(other_user)
        self.assertTrue(instance.can_edit(other_user))


class TestWorkflowTask(TestCase):
    """Test WorkflowTask model"""
    
    def setUp(self):
        from accounts.models import Group
        self.group = Group.objects.create(
            name='Test Company',
            slug='test-company'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        self.user.group = self.group
        self.user.save()
        
        self.definition = WorkflowDefinition.objects.create(
            workflow_id='test.workflow',
            name='Test Workflow',
            group=self.group
        )
        
        self.instance = WorkflowInstance.objects.create(
            definition=self.definition,
            started_by=self.user,
            group=self.group
        )
    
    def test_create_workflow_task(self):
        """Test creating a workflow task"""
        task = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task-1',
            name='Test Task',
            description='A test task',
            task_type='user',
            assigned_to=self.user,
            priority='medium',
            due_date=timezone.now() + timedelta(days=1),
            group=self.group
        )
        
        self.assertEqual(task.task_id, 'task-1')
        self.assertEqual(task.name, 'Test Task')
        self.assertEqual(task.status, 'created')
        self.assertEqual(task.task_type, 'user')
        self.assertEqual(task.priority, 'medium')
        self.assertFalse(task.is_overdue())
    
    def test_task_status_transitions(self):
        """Test task status transitions"""
        task = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task-2',
            name='Test Task',
            assigned_to=self.user,
            group=self.group
        )
        
        # Assign task
        task.assign(user=self.user)
        self.assertEqual(task.status, 'assigned')
        
        # Start task
        task.start(user=self.user)
        self.assertEqual(task.status, 'started')
        self.assertIsNotNone(task.started_at)
        
        # Complete task
        task.complete(user=self.user, output_data={'result': 'done'})
        self.assertEqual(task.status, 'completed')
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.completed_by, self.user)
        self.assertEqual(task.output_data['result'], 'done')
    
    def test_task_skip(self):
        """Test task skipping"""
        task = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task-3',
            name='Optional Task',
            status='assigned',
            group=self.group
        )
        
        task.skip(reason='Not required')
        self.assertEqual(task.status, 'skipped')
        self.assertEqual(task.error_message, 'Skipped: Not required')
    
    def test_task_fail(self):
        """Test task failure"""
        task = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task-4',
            name='Test Task',
            status='started',
            group=self.group
        )
        
        task.fail(error_message='Processing error')
        self.assertEqual(task.status, 'failed')
        self.assertEqual(task.error_message, 'Processing error')
    
    def test_task_dependencies(self):
        """Test task dependencies"""
        task1 = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task-dep-1',
            name='Task 1',
            status='completed',
            group=self.group
        )
        
        task2 = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task-dep-2',
            name='Task 2',
            status='assigned',
            group=self.group
        )
        
        task3 = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task-dep-3',
            name='Task 3',
            group=self.group
        )
        
        # Add dependencies
        task3.depends_on.add(task1, task2)
        
        # Check can_start
        self.assertFalse(task3.can_start())  # task2 not completed
        
        # Complete task2
        task2.status = 'completed'
        task2.save()
        
        self.assertTrue(task3.can_start())  # All dependencies completed
    
    def test_is_overdue(self):
        """Test overdue detection"""
        # Create overdue task
        task = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='overdue-task',
            name='Overdue Task',
            due_date=timezone.now() - timedelta(hours=1),
            status='assigned',
            group=self.group
        )
        
        self.assertTrue(task.is_overdue())
        
        # Complete task
        task.status = 'completed'
        task.save()
        
        self.assertFalse(task.is_overdue())  # Completed tasks not overdue


class TestWorkflowTransition(TestCase):
    """Test WorkflowTransition model"""
    
    def setUp(self):
        from accounts.models import Group
        self.group = Group.objects.create(
            name='Test Company',
            slug='test-company'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        self.definition = WorkflowDefinition.objects.create(
            workflow_id='test.workflow',
            name='Test Workflow',
            group=self.group
        )
        
        self.instance = WorkflowInstance.objects.create(
            definition=self.definition,
            started_by=self.user,
            group=self.group
        )
        
        self.task1 = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task1',
            name='Task 1',
            group=self.group
        )
        
        self.task2 = WorkflowTask.objects.create(
            workflow=self.instance,
            task_id='task2',
            name='Task 2',
            group=self.group
        )
    
    def test_create_transition(self):
        """Test creating a transition"""
        transition = WorkflowTransition.objects.create(
            workflow=self.instance,
            from_task=self.task1,
            to_task=self.task2,
            transition_type='sequence',
            condition='output.approved == true'
        )
        
        self.assertEqual(transition.from_task, self.task1)
        self.assertEqual(transition.to_task, self.task2)
        self.assertEqual(transition.transition_type, 'sequence')
        self.assertIsNotNone(transition.condition)
    
    def test_transition_str(self):
        """Test string representation"""
        transition = WorkflowTransition.objects.create(
            workflow=self.instance,
            from_task=self.task1,
            to_task=self.task2
        )
        
        expected = f"{self.instance.instance_id}: Task 1 → Task 2"
        self.assertEqual(str(transition), expected)


class TestWorkflowTemplate(TestCase):
    """Test WorkflowTemplate model"""
    
    def setUp(self):
        from accounts.models import Group
        self.group = Group.objects.create(
            name='Test Company',
            slug='test-company'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        self.user.group = self.group
        self.user.save()
        
        self.definition = WorkflowDefinition.objects.create(
            workflow_id='test.template',
            name='Template Workflow',
            group=self.group
        )
    
    def test_create_template(self):
        """Test creating a workflow template"""
        template = WorkflowTemplate.objects.create(
            template_id='approval-template',
            name='Approval Template',
            description='Standard approval workflow',
            category='approvals',
            definition=self.definition,
            customizable_fields=['timeout', 'approvers'],
            default_values={
                'timeout': 86400,
                'approvers': ['manager']
            },
            estimated_duration=timedelta(days=2),
            group=self.group
        )
        
        self.assertEqual(template.template_id, 'approval-template')
        self.assertEqual(template.name, 'Approval Template')
        self.assertEqual(template.category, 'approvals')
        self.assertTrue(template.is_active)
        self.assertEqual(template.times_used, 0)
    
    def test_create_instance_from_template(self):
        """Test creating instance from template"""
        template = WorkflowTemplate.objects.create(
            template_id='test-template',
            name='Test Template',
            definition=self.definition,
            customizable_fields=['field1', 'field2'],
            default_values={
                'field1': 'default1',
                'field2': 'default2'
            },
            group=self.group
        )
        
        # Create instance
        instance = template.create_instance(
            title='From Template',
            user=self.user,
            field1='custom1'
        )
        
        self.assertIsNotNone(instance)
        self.assertEqual(instance.title, 'From Template')
        self.assertEqual(instance.definition, self.definition)
        self.assertEqual(instance.started_by, self.user)
        self.assertEqual(instance.context_data['field1'], 'custom1')
        self.assertEqual(instance.context_data['field2'], 'default2')  # Default value
        
        # Check template usage updated
        template.refresh_from_db()
        self.assertEqual(template.times_used, 1)
    
    def test_template_str(self):
        """Test string representation"""
        template = WorkflowTemplate.objects.create(
            template_id='test-template',
            name='Test Template',
            definition=self.definition,
            group=self.group
        )
        
        self.assertEqual(str(template), 'Test Template (test-template)')