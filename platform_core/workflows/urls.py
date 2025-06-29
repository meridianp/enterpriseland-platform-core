from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    WorkflowDefinitionViewSet,
    WorkflowInstanceViewSet,
    WorkflowTaskViewSet,
    WorkflowTemplateViewSet
)

app_name = 'workflows'
router = DefaultRouter()

# Register viewsets
router.register(r'definitions', WorkflowDefinitionViewSet, basename='workflow-definition')
router.register(r'instances', WorkflowInstanceViewSet, basename='workflow-instance')
router.register(r'tasks', WorkflowTaskViewSet, basename='workflow-task')
router.register(r'templates', WorkflowTemplateViewSet, basename='workflow-template')

urlpatterns = [
    path('api/workflows/', include(router.urls)),
]
