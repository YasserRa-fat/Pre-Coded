from django.core.management.base import BaseCommand
from core.early import dynamic_register_apps_early

class Command(BaseCommand):
    help = 'Register dynamic apps early'

    def handle(self, *args, **options):
        dynamic_register_apps_early()
        self.stdout.write(self.style.SUCCESS('Dynamic apps registered successfully'))