"""URL configuration for document management module."""

from django.urls import path, include

app_name = 'documents'

urlpatterns = [
    # API v1
    path('api/v1/', include('business_modules.documents.api.v1.urls')),
    
    # Public shared links (no auth required)
    path('shared/<str:token>/', 'business_modules.documents.views.shared_link_view', name='shared-link'),
]