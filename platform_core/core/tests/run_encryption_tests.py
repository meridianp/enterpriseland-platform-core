#!/usr/bin/env python
"""
Convenience script to run all encryption-related tests.

Usage:
    python run_encryption_tests.py              # Run all encryption tests
    python run_encryption_tests.py fields       # Run only field tests
    python run_encryption_tests.py --verbose    # Run with verbose output
    python run_encryption_tests.py --coverage   # Run with coverage report
"""

import os
import sys
import subprocess
from pathlib import Path

# Add backend directory to Python path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Test modules
TEST_MODULES = {
    'fields': 'core.tests.test_encryption_fields',
    'rotation': 'core.tests.test_encryption_key_rotation',
    'search': 'core.tests.test_encryption_search',
    'bulk': 'core.tests.test_encryption_bulk_operations',
    'migration': 'core.tests.test_encryption_migration',
    'command': 'core.tests.test_encryption_management_command',
    'integration': 'core.tests.test_encryption_integration',
}

ALL_TESTS = [
    'core.tests.test_encryption_fields',
    'core.tests.test_encryption_key_rotation',
    'core.tests.test_encryption_search',
    'core.tests.test_encryption_bulk_operations',
    'core.tests.test_encryption_migration',
    'core.tests.test_encryption_management_command',
    'core.tests.test_encryption_integration',
]


def run_tests(test_modules, verbose=False, with_coverage=False):
    """Run the specified test modules."""
    os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
    
    # Build command
    if with_coverage:
        cmd = ['coverage', 'run', '--source=core.encryption', 'manage.py', 'test']
    else:
        cmd = ['python', 'manage.py', 'test']
    
    if verbose:
        cmd.append('--verbosity=2')
    
    cmd.extend(test_modules)
    
    # Run tests
    print(f"Running tests: {' '.join(test_modules)}")
    print("-" * 80)
    
    result = subprocess.run(cmd, cwd=backend_dir)
    
    # Show coverage report if requested
    if with_coverage and result.returncode == 0:
        print("\n" + "=" * 80)
        print("Coverage Report:")
        print("=" * 80)
        subprocess.run(['coverage', 'report', '--show-missing'], cwd=backend_dir)
        
        # Generate HTML report
        subprocess.run(['coverage', 'html'], cwd=backend_dir)
        print(f"\nDetailed HTML coverage report generated in: {backend_dir}/htmlcov/")
    
    return result.returncode


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Run encryption framework tests',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                    # Run all encryption tests
    %(prog)s fields             # Run only field tests
    %(prog)s fields search      # Run field and search tests
    %(prog)s --verbose          # Run with verbose output
    %(prog)s --coverage         # Run with coverage report
    %(prog)s -vc fields         # Verbose with coverage for field tests
        """
    )
    
    parser.add_argument(
        'modules',
        nargs='*',
        choices=list(TEST_MODULES.keys()) + ['all'],
        default=['all'],
        help='Test modules to run (default: all)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Run tests with verbose output'
    )
    
    parser.add_argument(
        '-c', '--coverage',
        action='store_true',
        help='Run tests with coverage report'
    )
    
    args = parser.parse_args()
    
    # Determine which tests to run
    if 'all' in args.modules or not args.modules:
        test_modules = ALL_TESTS
    else:
        test_modules = [TEST_MODULES[module] for module in args.modules]
    
    # Run the tests
    exit_code = run_tests(test_modules, args.verbose, args.coverage)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()