#!/usr/bin/env python3
"""
Database migration script for platform core
"""
import os
import django
from django.core.management import execute_from_command_line

def run_migrations():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_core.settings')
    django.setup()
    
    # Create migrations
    execute_from_command_line(['manage.py', 'makemigrations'])
    
    # Apply migrations  
    execute_from_command_line(['manage.py', 'migrate'])
    
    print("✅ Platform core migrations completed")

if __name__ == '__main__':
    run_migrations()
