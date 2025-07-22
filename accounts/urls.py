
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    CustomTokenObtainPairView, UserViewSet, GroupViewSet,
    GuestAccessViewSet, guest_login, logout
)
from .cookie_views import (
    cookie_login, cookie_refresh, cookie_logout, get_csrf_token
)
from .auth_views import (
    login_view, refresh_view, logout_view, me_view, 
    csrf_token_view, verify_token_view, complete_mfa_login_view
)
from .mfa_views import (
    mfa_status, setup_totp, verify_totp_setup, disable_mfa,
    verify_mfa, get_backup_codes, regenerate_backup_codes
)

router = DefaultRouter()
router.register(r'users', UserViewSet)
router.register(r'groups', GroupViewSet)
router.register(r'guest-access', GuestAccessViewSet)

urlpatterns = [
    # Unified auth endpoints (supports both JWT and cookie modes)
    path('auth/login/', login_view, name='auth_login'),
    path('auth/refresh/', refresh_view, name='auth_refresh'),
    path('auth/logout/', logout_view, name='auth_logout'),
    path('auth/me/', me_view, name='auth_me'),
    path('auth/csrf/', csrf_token_view, name='auth_csrf'),
    path('auth/verify/', verify_token_view, name='auth_verify'),
    
    # MFA endpoints
    path('auth/mfa/status/', mfa_status, name='mfa_status'),
    path('auth/mfa/setup/totp/', setup_totp, name='setup_totp'),
    path('auth/mfa/verify/totp/', verify_totp_setup, name='verify_totp_setup'),
    path('auth/mfa/verify/', verify_mfa, name='verify_mfa'),
    path('auth/mfa/complete/', complete_mfa_login_view, name='complete_mfa_login'),
    path('auth/mfa/disable/', disable_mfa, name='disable_mfa'),
    path('auth/mfa/backup-codes/', get_backup_codes, name='get_backup_codes'),
    path('auth/mfa/backup-codes/regenerate/', regenerate_backup_codes, name='regenerate_backup_codes'),
    
    # Cookie-based auth endpoints (legacy - to be deprecated)
    path('cookie/login/', cookie_login, name='cookie_login'),
    path('cookie/refresh/', cookie_refresh, name='cookie_refresh'),
    path('cookie/logout/', cookie_logout, name='cookie_logout'),
    path('cookie/csrf/', get_csrf_token, name='get_csrf_token'),
    
    # JWT token-based endpoints (legacy - to be deprecated)
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', logout, name='logout'),
    path('guest-login/', guest_login, name='guest_login'),
    
    path('', include(router.urls)),
]
