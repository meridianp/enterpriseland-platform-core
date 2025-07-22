"""
Platform Core Accounts App

Provides authentication, authorization, and multi-tenancy support
for the EnterpriseLand platform.

This is the platform-level accounts app that provides:
- User authentication with multiple roles
- Group-based multi-tenancy
- Security features (MFA, device tracking, etc.)
"""

default_app_config = 'platform_core.accounts.apps.AccountsConfig'