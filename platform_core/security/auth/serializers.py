"""
Authentication Serializers

Enhanced serializers for authentication operations.
"""

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import MFADevice, AuthSession, OAuth2Client
from .authentication import (
    EnhancedRefreshToken, create_auth_session, 
    check_concurrent_sessions, get_client_ip
)


User = get_user_model()


class EnhancedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Enhanced token obtain serializer with MFA support.
    """
    
    mfa_code = serializers.CharField(
        required=False,
        help_text=_("MFA code if user has MFA enabled")
    )
    
    def validate(self, attrs):
        """Validate credentials and MFA if required"""
        # First validate username/password
        data = super().validate(attrs)
        
        # Check if user has MFA enabled
        user = self.user
        if self._is_mfa_required(user):
            mfa_code = attrs.get('mfa_code')
            if not mfa_code:
                raise serializers.ValidationError({
                    'mfa_required': True,
                    'mfa_types': self._get_available_mfa_types(user)
                })
            
            if not self._validate_mfa_code(user, mfa_code):
                raise serializers.ValidationError({
                    'mfa_code': _('Invalid MFA code')
                })
        
        # Check concurrent sessions
        if not check_concurrent_sessions(user):
            raise serializers.ValidationError({
                'error': _('Maximum concurrent sessions exceeded')
            })
        
        # Create session tracking
        request = self.context.get('request')
        session = create_auth_session(user, request)
        
        # Add session ID to token
        data['access'].payload['session_id'] = session.session_key
        data['refresh'].payload['session_id'] = session.session_key
        
        # Add additional claims
        data['access'].payload['group_id'] = str(user.group.id) if hasattr(user, 'group') else None
        data['refresh'].payload['group_id'] = str(user.group.id) if hasattr(user, 'group') else None
        
        return data
    
    def _is_mfa_required(self, user):
        """Check if MFA is required for user"""
        return MFADevice.objects.filter(
            user=user,
            is_active=True
        ).exists()
    
    def _get_available_mfa_types(self, user):
        """Get available MFA types for user"""
        return list(MFADevice.objects.filter(
            user=user,
            is_active=True
        ).values_list('device_type', flat=True).distinct())
    
    def _validate_mfa_code(self, user, code):
        """Validate MFA code"""
        # Try primary device first
        primary_device = MFADevice.objects.filter(
            user=user,
            is_active=True,
            is_primary=True
        ).first()
        
        if primary_device:
            if self._check_device_code(primary_device, code):
                primary_device.mark_used()
                return True
        
        # Try other devices
        for device in MFADevice.objects.filter(user=user, is_active=True):
            if self._check_device_code(device, code):
                device.mark_used()
                return True
        
        return False
    
    def _check_device_code(self, device, code):
        """Check code against specific device"""
        if device.device_type == 'totp':
            # Validate TOTP code
            import pyotp
            totp = pyotp.TOTP(device.secret_key)
            return totp.verify(code, valid_window=1)
        
        elif device.device_type == 'backup':
            # Check backup codes
            if code in device.backup_codes:
                # Remove used code
                device.backup_codes.remove(code)
                device.save()
                return True
        
        # Other device types would be implemented here
        return False


class EnhancedTokenRefreshSerializer(TokenRefreshSerializer):
    """
    Enhanced token refresh with rotation.
    """
    
    def validate(self, attrs):
        """Validate and rotate refresh token"""
        refresh = EnhancedRefreshToken(attrs['refresh'])
        
        # Rotate the refresh token
        request = self.context.get('request')
        new_refresh = refresh.rotate(request)
        
        # Get new access token
        data = {
            'access': str(new_refresh.access_token),
            'refresh': str(new_refresh)
        }
        
        return data


class MFADeviceSerializer(serializers.ModelSerializer):
    """Serializer for MFA devices"""
    
    class Meta:
        model = MFADevice
        fields = [
            'id', 'name', 'device_type', 'is_primary',
            'is_active', 'last_used', 'created_at'
        ]
        read_only_fields = ['id', 'last_used', 'created_at']


class SetupTOTPSerializer(serializers.Serializer):
    """Serializer for TOTP setup"""
    
    name = serializers.CharField(
        max_length=100,
        help_text=_("Device name")
    )
    
    def create(self, validated_data):
        """Create TOTP device"""
        import pyotp
        import qrcode
        import io
        import base64
        
        user = self.context['request'].user
        
        # Generate secret
        secret = pyotp.random_base32()
        
        # Create device
        device = MFADevice.objects.create(
            user=user,
            group=user.group if hasattr(user, 'group') else None,
            name=validated_data['name'],
            device_type='totp',
            secret_key=secret,
            is_primary=not MFADevice.objects.filter(user=user, is_active=True).exists()
        )
        
        # Generate QR code
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email,
            issuer_name='EnterpriseLand Platform'
        )
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        qr_code = base64.b64encode(buffer.getvalue()).decode()
        
        return {
            'device': MFADeviceSerializer(device).data,
            'secret': secret,
            'qr_code': f'data:image/png;base64,{qr_code}',
            'backup_codes': device.generate_backup_codes()
        }


class VerifyTOTPSerializer(serializers.Serializer):
    """Verify TOTP code"""
    
    device_id = serializers.IntegerField()
    code = serializers.CharField(max_length=6)
    
    def validate(self, attrs):
        """Validate TOTP code"""
        user = self.context['request'].user
        
        try:
            device = MFADevice.objects.get(
                id=attrs['device_id'],
                user=user,
                device_type='totp',
                is_active=False  # Only verify inactive devices
            )
        except MFADevice.DoesNotExist:
            raise serializers.ValidationError(_("Device not found"))
        
        # Verify code
        import pyotp
        totp = pyotp.TOTP(device.secret_key)
        if not totp.verify(attrs['code']):
            raise serializers.ValidationError(_("Invalid code"))
        
        # Activate device
        device.is_active = True
        device.save()
        
        return {'device': device}


class AuthSessionSerializer(serializers.ModelSerializer):
    """Serializer for auth sessions"""
    
    device_description = serializers.SerializerMethodField()
    
    class Meta:
        model = AuthSession
        fields = [
            'id', 'created_at', 'last_activity', 'expires_at',
            'ip_address', 'device_description', 'location_info',
            'is_active'
        ]
        read_only_fields = fields
    
    def get_device_description(self, obj):
        """Get human-readable device description"""
        info = obj.device_info
        if not info:
            return obj.user_agent
        
        parts = []
        if info.get('browser'):
            parts.append(f"{info['browser']} {info.get('browser_version', '')}")
        if info.get('os'):
            parts.append(f"{info['os']} {info.get('os_version', '')}")
        if info.get('device') and info['device'] != 'Other':
            parts.append(info['device'])
        
        return ' - '.join(parts).strip()


class OAuth2ClientSerializer(serializers.ModelSerializer):
    """Serializer for OAuth2 clients"""
    
    class Meta:
        model = OAuth2Client
        fields = [
            'id', 'client_id', 'name', 'description',
            'client_type', 'redirect_uris', 'allowed_scopes',
            'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'client_id', 'created_at']
        extra_kwargs = {
            'client_secret': {'write_only': True}
        }
    
    def create(self, validated_data):
        """Create OAuth2 client with generated credentials"""
        import secrets
        
        # Generate client ID and secret
        validated_data['client_id'] = f"client_{secrets.token_urlsafe(16)}"
        validated_data['client_secret'] = secrets.token_urlsafe(32)
        
        # Set creator
        validated_data['created_by'] = self.context['request'].user
        
        # Add group if available
        user = self.context['request'].user
        if hasattr(user, 'group'):
            validated_data['group'] = user.group
        
        return super().create(validated_data)