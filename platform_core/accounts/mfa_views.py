"""
Multi-Factor Authentication views
"""
import pyotp
import qrcode
import io
import base64
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import User, MFAMethod, MFABackupCode, SecurityEvent
from .serializers import MFAMethodSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mfa_status(request):
    """
    Get MFA status for current user
    
    GET /api/auth/mfa/status/
    """
    user = request.user
    methods = MFAMethod.objects.filter(user=user, is_active=True)
    
    return Response({
        'mfa_enabled': methods.exists(),
        'methods': MFAMethodSerializer(methods, many=True).data,
        'primary_method': MFAMethodSerializer(methods.filter(is_primary=True).first()).data if methods.exists() else None,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def setup_totp(request):
    """
    Setup TOTP (Time-based One-Time Password) for user
    
    POST /api/auth/mfa/setup/totp/
    """
    user = request.user
    
    # Check if TOTP is already set up
    existing = MFAMethod.objects.filter(
        user=user,
        method=MFAMethod.Method.TOTP,
        is_active=True
    ).first()
    
    if existing:
        return Response(
            {'error': 'TOTP is already configured'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Generate secret
    secret = pyotp.random_base32()
    
    # Generate provisioning URI
    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name=settings.SITE_NAME if hasattr(settings, 'SITE_NAME') else 'EnterpriseLand'
    )
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    # Store secret temporarily in cache (10 minutes)
    cache_key = f"mfa_setup:{user.id}:totp"
    cache.set(cache_key, secret, timeout=600)
    
    return Response({
        'secret': secret,
        'qr_code': f"data:image/png;base64,{qr_code_base64}",
        'manual_entry_key': secret,
        'manual_entry_uri': totp_uri,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_totp_setup(request):
    """
    Verify TOTP setup with a code
    
    POST /api/auth/mfa/verify/totp/
    {
        "code": "123456"
    }
    """
    user = request.user
    code = request.data.get('code')
    
    if not code:
        return Response(
            {'error': 'Verification code is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get secret from cache
    cache_key = f"mfa_setup:{user.id}:totp"
    secret = cache.get(cache_key)
    
    if not secret:
        return Response(
            {'error': 'Setup session expired. Please start over.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify code
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return Response(
            {'error': 'Invalid verification code'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Create MFA method
    mfa_method = MFAMethod.objects.create(
        user=user,
        method=MFAMethod.Method.TOTP,
        secret=secret,
        verified_at=timezone.now(),
        is_primary=not MFAMethod.objects.filter(user=user, is_active=True).exists()
    )
    
    # Generate backup codes
    backup_codes = []
    for _ in range(10):
        code = pyotp.random_base32()[:8]
        MFABackupCode.objects.create(user=user, code=code)
        backup_codes.append(code)
    
    # Clear cache
    cache.delete(cache_key)
    
    # Log security event
    SecurityEvent.objects.create(
        user=user,
        event_type=SecurityEvent.EventType.MFA_ENABLED,
        description=f"TOTP authentication enabled",
        ip_address=request.META.get('REMOTE_ADDR', ''),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
    )
    
    return Response({
        'message': 'TOTP authentication enabled successfully',
        'backup_codes': backup_codes,
        'method': MFAMethodSerializer(mfa_method).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disable_mfa(request):
    """
    Disable MFA method
    
    POST /api/auth/mfa/disable/
    {
        "method_id": "uuid",
        "password": "current_password"
    }
    """
    user = request.user
    method_id = request.data.get('method_id')
    password = request.data.get('password')
    
    if not password:
        return Response(
            {'error': 'Password is required to disable MFA'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify password
    if not user.check_password(password):
        return Response(
            {'error': 'Invalid password'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    try:
        mfa_method = MFAMethod.objects.get(id=method_id, user=user, is_active=True)
        mfa_method.is_active = False
        mfa_method.save()
        
        # If this was the primary method, set another as primary
        if mfa_method.is_primary:
            next_method = MFAMethod.objects.filter(
                user=user,
                is_active=True
            ).exclude(id=mfa_method.id).first()
            
            if next_method:
                next_method.is_primary = True
                next_method.save()
        
        # Log security event
        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEvent.EventType.MFA_DISABLED,
            description=f"{mfa_method.get_method_display()} authentication disabled",
            ip_address=request.META.get('REMOTE_ADDR', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
        
        return Response({'message': 'MFA method disabled successfully'})
        
    except MFAMethod.DoesNotExist:
        return Response(
            {'error': 'MFA method not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
@permission_classes([])
def verify_mfa(request):
    """
    Verify MFA code during login
    
    POST /api/auth/mfa/verify/
    {
        "user_id": "uuid",
        "code": "123456",
        "method": "totp"  // or "backup_code"
    }
    """
    user_id = request.data.get('user_id')
    code = request.data.get('code')
    method_type = request.data.get('method', 'totp')
    
    if not user_id or not code:
        return Response(
            {'error': 'User ID and code are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response(
            {'error': 'Invalid user'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify based on method type
    if method_type == 'backup_code':
        # Check backup codes
        backup_code = MFABackupCode.objects.filter(
            user=user,
            code=code,
            used_at__isnull=True
        ).first()
        
        if backup_code:
            backup_code.use()
            verified = True
        else:
            verified = False
    else:
        # Verify TOTP
        mfa_method = MFAMethod.objects.filter(
            user=user,
            method=MFAMethod.Method.TOTP,
            is_active=True
        ).first()
        
        if not mfa_method:
            return Response(
                {'error': 'MFA not configured'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        totp = pyotp.TOTP(mfa_method.secret)
        verified = totp.verify(code, valid_window=1)
        
        if verified:
            # Update last used
            mfa_method.last_used_at = timezone.now()
            mfa_method.use_count += 1
            mfa_method.save()
    
    if verified:
        # Generate session token for completed MFA
        session_token = pyotp.random_base32()
        cache_key = f"mfa_verified:{user.id}"
        cache.set(cache_key, session_token, timeout=300)  # 5 minutes
        
        return Response({
            'verified': True,
            'session_token': session_token,
        })
    else:
        # Log failed attempt
        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEvent.EventType.MFA_FAILED,
            description=f"Failed MFA attempt using {method_type}",
            ip_address=request.META.get('REMOTE_ADDR', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
        
        return Response(
            {'error': 'Invalid verification code'},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_backup_codes(request):
    """
    Get remaining backup codes count
    
    GET /api/auth/mfa/backup-codes/
    """
    user = request.user
    remaining = MFABackupCode.objects.filter(
        user=user,
        used_at__isnull=True
    ).count()
    
    return Response({
        'remaining_codes': remaining,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_backup_codes(request):
    """
    Regenerate backup codes
    
    POST /api/auth/mfa/backup-codes/regenerate/
    {
        "password": "current_password"
    }
    """
    user = request.user
    password = request.data.get('password')
    
    if not password:
        return Response(
            {'error': 'Password is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify password
    if not user.check_password(password):
        return Response(
            {'error': 'Invalid password'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    # Check if user has MFA enabled
    if not MFAMethod.objects.filter(user=user, is_active=True).exists():
        return Response(
            {'error': 'MFA is not enabled'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Delete old codes
    MFABackupCode.objects.filter(user=user).delete()
    
    # Generate new codes
    backup_codes = []
    for _ in range(10):
        code = pyotp.random_base32()[:8]
        MFABackupCode.objects.create(user=user, code=code)
        backup_codes.append(code)
    
    return Response({
        'message': 'Backup codes regenerated successfully',
        'backup_codes': backup_codes,
    })