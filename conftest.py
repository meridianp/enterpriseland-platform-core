"""
Test configuration for platform-core
"""

import os
import sys
import django

# Add platform-core to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure Django settings for tests
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'test_settings')

# This will be called by pytest-django
def pytest_configure():
    django.setup()