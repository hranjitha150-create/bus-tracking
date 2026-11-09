from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from tracking.models import LocationHistory


class Command(BaseCommand):
    help = 'Prune GPS history older than LOCATION_HISTORY_RETENTION_DAYS; retain latest locations and route progress.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=settings.LOCATION_HISTORY_RETENTION_DAYS)
        count = 0
        while True:
            ids = list(LocationHistory.objects.filter(received_at__lt=cutoff).order_by('pk').values_list('pk', flat=True)[:5000])
            if not ids:
                break
            count += LocationHistory.objects.filter(pk__in=ids).delete()[0]
        self.stdout.write(f'Pruned {count} old location history records. Latest positions and progress were preserved.')
