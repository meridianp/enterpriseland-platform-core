"""
Test runner and configuration for API Key tests.

Provides utilities for running comprehensive test suites with coverage reporting.
"""

import os
import sys
import django
from django.conf import settings
from django.test.utils import get_runner
from django.core.management import execute_from_command_line


def run_api_key_tests():
    """Run all API key tests with coverage reporting."""
    
    # Test modules to run
    test_modules = [
        'api_keys.tests',
        'api_keys.test_commands',
        'api_keys.test_serializers', 
        'api_keys.test_security',
    ]
    
    # Set up Django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.test')
    django.setup()
    
    # Run tests with coverage
    commands = [
        'manage.py',
        'test',
        '--verbosity=2',
        '--failfast',
        '--parallel',
        '--debug-mode',
    ] + test_modules
    
    execute_from_command_line(commands)


def run_with_coverage():
    """Run tests with coverage reporting."""
    try:
        import coverage
    except ImportError:
        print("Coverage.py not installed. Install with: pip install coverage")
        sys.exit(1)
    
    # Start coverage
    cov = coverage.Coverage(
        source=['api_keys'],
        omit=[
            '*/tests*',
            '*/venv/*',
            '*/migrations/*',
            '*/__pycache__/*',
        ]
    )
    cov.start()
    
    try:
        run_api_key_tests()
    finally:
        # Stop coverage and generate report
        cov.stop()
        cov.save()
        
        print("\n" + "="*50)
        print("COVERAGE REPORT")
        print("="*50)
        cov.report(show_missing=True)
        
        # Generate HTML report
        cov.html_report(directory='htmlcov')
        print(f"\nHTML coverage report generated in 'htmlcov' directory")


def run_security_tests_only():
    """Run only security-focused tests."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.test')
    django.setup()
    
    commands = [
        'manage.py',
        'test',
        '--verbosity=2',
        '--failfast',
        'api_keys.test_security',
    ]
    
    execute_from_command_line(commands)


def run_performance_tests():
    """Run performance-focused tests."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.test')
    django.setup()
    
    commands = [
        'manage.py',
        'test',
        '--verbosity=2',
        '--failfast',
        'api_keys.tests.APIKeyPerformanceTests',
        'api_keys.test_serializers.SerializerPerformanceTests',
    ]
    
    execute_from_command_line(commands)


def run_integration_tests():
    """Run integration tests only."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.test')
    django.setup()
    
    commands = [
        'manage.py',
        'test',
        '--verbosity=2',
        '--failfast',
        'api_keys.tests.APIKeyIntegrationTests',
        'api_keys.tests.APIKeyViewSetTests',
        'api_keys.test_commands.CommandIntegrationTests',
    ]
    
    execute_from_command_line(commands)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Run API Key tests')
    parser.add_argument(
        '--coverage', 
        action='store_true', 
        help='Run with coverage reporting'
    )
    parser.add_argument(
        '--security', 
        action='store_true', 
        help='Run only security tests'
    )
    parser.add_argument(
        '--performance', 
        action='store_true', 
        help='Run only performance tests'
    )
    parser.add_argument(
        '--integration', 
        action='store_true', 
        help='Run only integration tests'
    )
    
    args = parser.parse_args()
    
    if args.coverage:
        run_with_coverage()
    elif args.security:
        run_security_tests_only()
    elif args.performance:
        run_performance_tests()
    elif args.integration:
        run_integration_tests()
    else:
        run_api_key_tests()