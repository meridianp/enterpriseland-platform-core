"""
Django management command for cache warming.

Proactively populates cache with frequently accessed data
to improve application performance.
"""

from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from platform_core.core.cache_strategies import CacheWarmer, ModelCacheStrategy


class Command(BaseCommand):
    help = 'Warm cache with frequently accessed data'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--models',
            nargs='+',
            help='Specific models to warm (format: app.ModelName)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Maximum number of instances to cache per model (default: 100)'
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=1800,
            help='Cache timeout in seconds (default: 1800)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be warmed without actually doing it'
        )
    
    def handle(self, *args, **options):
        models_to_warm = options.get('models')
        limit = options['limit']
        timeout = options['timeout']
        dry_run = options['dry_run']
        
        try:
            warmer = CacheWarmer()
            total_cached = 0
            
            if models_to_warm:
                # Warm specific models
                for model_name in models_to_warm:
                    try:
                        app_label, model_class_name = model_name.split('.')
                        model_class = apps.get_model(app_label, model_class_name)
                        
                        if dry_run:
                            count = model_class.objects.count()
                            limited_count = min(count, limit)
                            self.stdout.write(
                                f"Would warm {limited_count} {model_class.__name__} instances"
                            )
                        else:
                            queryset = model_class.objects.all()[:limit]
                            cached_count = warmer.warm_model_cache(
                                model_class, queryset, timeout
                            )
                            total_cached += cached_count
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Warmed {cached_count} {model_class.__name__} instances"
                                )
                            )
                    
                    except ValueError:
                        raise CommandError(
                            f"Invalid model format: {model_name}. Use format: app.ModelName"
                        )
                    except LookupError:
                        raise CommandError(f"Model not found: {model_name}")
            
            else:
                # Warm default models
                default_models = self._get_default_models()
                
                for model_class in default_models:
                    try:
                        if dry_run:
                            count = model_class.objects.count()
                            limited_count = min(count, limit)
                            self.stdout.write(
                                f"Would warm {limited_count} {model_class.__name__} instances"
                            )
                        else:
                            queryset = model_class.objects.all()[:limit]
                            cached_count = warmer.warm_model_cache(
                                model_class, queryset, timeout
                            )
                            total_cached += cached_count
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Warmed {cached_count} {model_class.__name__} instances"
                                )
                            )
                    except Exception as e:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Failed to warm {model_class.__name__}: {e}"
                            )
                        )
            
            if not dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nCache warming completed. Total instances cached: {total_cached}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("\nDry run completed. No cache operations performed.")
                )
        
        except Exception as e:
            raise CommandError(f"Error during cache warming: {e}")
    
    def _get_default_models(self):
        """
        Get list of default models to warm.
        
        Returns:
            List of model classes
        """
        default_models = []
        
        try:
            # Import models that are commonly accessed
            from contacts.models import Contact
            from accounts.models import User, Group
            
            default_models.extend([Contact, User, Group])
            
            # Try to import assessment models
            try:
                from assessments.models import DevelopmentPartnerAssessment
                default_models.append(DevelopmentPartnerAssessment)
            except ImportError:
                pass
            
            # Try to import leads models
            try:
                from leads.models import Lead, LeadScoringModel
                default_models.extend([Lead, LeadScoringModel])
            except ImportError:
                pass
            
            # Try to import market intelligence models
            try:
                from market_intelligence.models import TargetCompany, NewsArticle
                default_models.extend([TargetCompany, NewsArticle])
            except ImportError:
                pass
        
        except ImportError as e:
            self.stdout.write(
                self.style.WARNING(f"Could not import some models: {e}")
            )
        
        return default_models