app_name = 'platform_files'


from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FileAttachmentViewSet

router = DefaultRouter()
router.register(r'attachments', FileAttachmentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
