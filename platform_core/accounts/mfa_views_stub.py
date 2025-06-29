"""
Stub MFA views for deployment without pyotp
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mfa_status(request):
    return Response({
        'mfa_enabled': False,
        'mfa_type': None,
        'message': 'MFA not configured in this deployment'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def setup_totp(request):
    return Response({
        'error': 'MFA setup not available in this deployment'
    }, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_totp_setup(request):
    return Response({
        'error': 'MFA verification not available in this deployment'
    }, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disable_mfa(request):
    return Response({
        'error': 'MFA management not available in this deployment'
    }, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_mfa(request):
    return Response({
        'error': 'MFA verification not available in this deployment'
    }, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_backup_codes(request):
    return Response({
        'error': 'Backup codes not available in this deployment'
    }, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_backup_codes(request):
    return Response({
        'error': 'Backup codes not available in this deployment'
    }, status=status.HTTP_501_NOT_IMPLEMENTED)