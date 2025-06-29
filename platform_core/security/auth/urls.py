"""
Authentication URLs
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    EnhancedTokenObtainPairView,
    EnhancedTokenRefreshView,
    LogoutView,
    MFADeviceViewSet,
    AuthSessionViewSet,
    OAuth2ClientViewSet
)

app_name = 'auth'

router = DefaultRouter()
router.register(r'mfa-devices', MFADeviceViewSet, basename='mfa-device')
router.register(r'sessions', AuthSessionViewSet, basename='auth-session')
router.register(r'oauth-clients', OAuth2ClientViewSet, basename='oauth-client')

urlpatterns = [
    # JWT endpoints
    path('token/', EnhancedTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', EnhancedTokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    
    # Include router URLs
    path('', include(router.urls)),
]